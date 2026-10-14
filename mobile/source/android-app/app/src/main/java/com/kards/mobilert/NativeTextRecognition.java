package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.util.concurrent.TimeUnit;

/** Bundled offline OCR; source image is decoded without scaling or cropping. */
final class NativeTextRecognition implements AutoCloseable {
    private final TextRecognizer recognizer = TextRecognition.getClient(
            new ChineseTextRecognizerOptions.Builder().build());

    JSONObject inspect(File file) throws Exception {
        Bitmap bitmap = BitmapFactory.decodeFile(file.getAbsolutePath());
        if (bitmap == null) throw new IllegalArgumentException("native_ocr_decode_failed");
        try {
            Text text = Tasks.await(recognizer.process(InputImage.fromBitmap(bitmap, 0)),
                    5, TimeUnit.SECONDS);
            JSONArray items = new JSONArray();
            for (Text.TextBlock block : text.getTextBlocks()) {
                for (Text.Line line : block.getLines()) {
                    Rect box = line.getBoundingBox();
                    if (box == null) continue;
                    Float confidence = line.getConfidence();
                    JSONArray points = new JSONArray()
                            .put(new JSONArray().put(box.left).put(box.top))
                            .put(new JSONArray().put(box.right).put(box.top))
                            .put(new JSONArray().put(box.right).put(box.bottom))
                            .put(new JSONArray().put(box.left).put(box.bottom));
                    items.put(new JSONObject().put("text", line.getText()).put("box", points)
                            .put("score", confidence == null ? JSONObject.NULL : confidence)
                            .put("score_available", confidence != null));
                }
            }
            return new JSONObject().put("items", items).put("width", bitmap.getWidth())
                    .put("height", bitmap.getHeight()).put("coordinate_space", "source_pixels")
                    .put("engine", "bundled_mlkit_chinese");
        } finally {
            bitmap.recycle();
        }
    }

    @Override public void close() { recognizer.close(); }
}
