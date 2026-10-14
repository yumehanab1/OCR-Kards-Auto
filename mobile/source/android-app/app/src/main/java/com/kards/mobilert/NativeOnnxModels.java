package com.kards.mobilert;

import android.content.Context;
import android.util.Base64;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;

/** Same OCR model bytes as the offline experiment, executed by Android ONNX Runtime. */
public final class NativeOnnxModels {
    private static NativeOnnxModels instance;
    private final OrtEnvironment environment = OrtEnvironment.getEnvironment();
    private final Map<String, OrtSession> sessions = new HashMap<>();
    private final Context context;
    private final JSONObject manifest;

    private NativeOnnxModels(Context context) throws Exception {
        this.context = context.getApplicationContext();
        manifest = new JSONObject(new String(asset("native-ocr/manifest.json"), StandardCharsets.UTF_8));
    }

    public static synchronized NativeOnnxModels get(Context context) throws Exception {
        if (instance == null) instance = new NativeOnnxModels(context);
        return instance;
    }

    public synchronized void warm() throws Exception {
        for (String model : new String[]{"det", "cls", "rec"}) session(model);
    }

    private byte[] asset(String name) throws Exception {
        try (InputStream input = context.getAssets().open(name);
             java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384];
            int size;
            while ((size = input.read(buffer)) != -1) output.write(buffer, 0, size);
            return output.toByteArray();
        }
    }

    private OrtSession session(String model) throws Exception {
        if (!(model.equals("det") || model.equals("rec") || model.equals("cls")))
            throw new IllegalArgumentException("unknown_native_ocr_model");
        OrtSession existing = sessions.get(model);
        if (existing != null) return existing;
        JSONObject spec = manifest.getJSONObject(model);
        byte[] data = asset("native-ocr/" + spec.getString("file"));
        StringBuilder digest = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(data)) digest.append(String.format("%02x", b & 255));
        if (!digest.toString().equals(spec.getString("sha256"))) throw new IllegalStateException("native_ocr_model_hash_mismatch");
        File file = new File(context.getFilesDir(), "native-ocr/" + spec.getString("sha256") + ".onnx");
        if (!file.getParentFile().isDirectory() && !file.getParentFile().mkdirs()) throw new IllegalStateException("native_ocr_model_directory");
        try (FileOutputStream output = new FileOutputStream(file)) { output.write(data); }
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(2); options.setInterOpNumThreads(1);
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
            existing = environment.createSession(file.getAbsolutePath(), options);
        }
        sessions.put(model, existing);
        return existing;
    }

    public synchronized String infer(String model, String inputBase64, String shapeJson) throws Exception {
        JSONArray inputShape = new JSONArray(shapeJson);
        if (inputShape.length() != 4) throw new IllegalArgumentException("native_ocr_tensor_rank");
        long[] shape = new long[4]; long count = 1;
        for (int i = 0; i < 4; i++) {
            shape[i] = inputShape.getLong(i);
            if (shape[i] <= 0 || shape[i] > 3200) throw new IllegalArgumentException("native_ocr_tensor_dimension");
            count = Math.multiplyExact(count, shape[i]);
        }
        if (shape[0] > 6 || shape[1] != 3 || count > 24_000_000)
            throw new IllegalArgumentException("native_ocr_tensor_budget");
        byte[] bytes = Base64.decode(inputBase64, Base64.NO_WRAP);
        if (bytes.length != count * 4) throw new IllegalArgumentException("native_ocr_tensor_bytes");
        FloatBuffer input = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        OrtSession session = session(model);
        try (OnnxTensor tensor = OnnxTensor.createTensor(environment, input, shape)) {
            Map<String, OnnxTensor> inputs = new HashMap<>();
            inputs.put(session.getInputNames().iterator().next(), tensor);
            try (OrtSession.Result outputs = session.run(inputs)) {
                OnnxTensor output = (OnnxTensor) outputs.get(0);
                FloatBuffer floats = output.getFloatBuffer();
                if (model.equals("rec")) {
                    // CTC uses only argmax and max probability along class axis.
                    // Perform those exact reductions here rather than serializing
                    // thousands of unused class probabilities per character.
                    long[] dims = output.getInfo().getShape();
                    if (dims.length != 3 || dims[2] != 6625) throw new IllegalStateException("native_ocr_rec_shape");
                    JSONArray indices = new JSONArray(), scores = new JSONArray();
                    for (int row = 0; row < dims[0] * dims[1]; row++) {
                        float best = Float.NEGATIVE_INFINITY; int index = 0;
                        for (int column = 0; column < dims[2]; column++) {
                            float value = floats.get();
                            if (!Float.isFinite(value)) throw new IllegalStateException("native_ocr_rec_nonfinite");
                            // NumPy argmax selects the first index in a tie.
                            if (value > best) { best = value; index = column; }
                        }
                        indices.put(index); scores.put((double) best);
                    }
                    return new JSONObject().put("ctc_compact", true)
                            .put("shape", new JSONArray().put(dims[0]).put(dims[1]))
                            .put("indices", indices).put("scores", scores).toString();
                }
                ByteBuffer binary = ByteBuffer.allocate(Math.multiplyExact(floats.remaining(), 4)).order(ByteOrder.LITTLE_ENDIAN);
                binary.asFloatBuffer().put(floats);
                JSONArray dimensions = new JSONArray();
                for (long dimension : output.getInfo().getShape()) dimensions.put(dimension);
                return new JSONObject().put("shape", dimensions)
                        .put("values", Base64.encodeToString(binary.array(), Base64.NO_WRAP)).toString();
            }
        }
    }

    /** Clipper 6 round closed-polygon offset, matching the desktop pyclipper step. */
    public String offsetPolygon(String pointsJson, double distance) throws Exception {
        JSONArray points = new JSONArray(pointsJson);
        if (points.length() != 4 || !Double.isFinite(distance) || distance <= 0 || distance > 3200)
            throw new IllegalArgumentException("native_ocr_offset_budget");
        de.lighti.clipper.Path polygon = new de.lighti.clipper.Path();
        for (int i = 0; i < points.length(); i++) {
            JSONArray point = points.getJSONArray(i);
            // pyclipper converts floating coordinates to Clipper integer coordinates by truncation.
            polygon.add(new de.lighti.clipper.Point.LongPoint((long) point.getDouble(0), (long) point.getDouble(1)));
        }
        de.lighti.clipper.ClipperOffset offset = new de.lighti.clipper.ClipperOffset();
        offset.addPath(polygon, de.lighti.clipper.Clipper.JoinType.ROUND,
                de.lighti.clipper.Clipper.EndType.CLOSED_POLYGON);
        de.lighti.clipper.Paths solution = new de.lighti.clipper.Paths();
        offset.execute(solution, distance);
        if (solution.size() != 1) throw new IllegalStateException("native_ocr_offset_not_unique");
        JSONArray result = new JSONArray();
        for (de.lighti.clipper.Point.LongPoint point : solution.get(0))
            result.put(new JSONArray().put(point.getX()).put(point.getY()));
        return result.toString();
    }
}
