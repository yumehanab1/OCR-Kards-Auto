package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Rect;
import com.chaquo.python.Python;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** No inputs: the bounded session retains freshness, pairing and foreground gates. */
final class NativeOpeningInspector implements BoundedMulliganSession.Inspector {
    private final Context context;
    private final File assets;
    NativeOpeningInspector(Context context) {
        this.context=context;assets=new File(context.getFilesDir(),"native-opening-component");
    }
    public MulliganRecognizer.Result inspect(Bitmap bitmap) { return inspectSource(bitmap, null); }
    @Override public MulliganRecognizer.Result inspectSaved(Bitmap bitmap, File source) {
        return inspectSource(bitmap, source);
    }
    private MulliganRecognizer.Result inspectSource(Bitmap bitmap, File source) {
        File frame=null;
        try {
            if (!NativeFrameCoordinates.valid(bitmap.getWidth(),bitmap.getHeight(),bitmap.getWidth(),bitmap.getHeight()))
                throw new IllegalArgumentException("invalid_source_geometry");
            if (!assets.isDirectory() && !assets.mkdirs()) throw new IllegalStateException("opening_assets");
            for (String name:context.getAssets().list("mulligan-one-shot")) {
                File file=new File(assets,name);
                if (file.isFile()) continue;
                try(InputStream in=context.getAssets().open("mulligan-one-shot/"+name);FileOutputStream out=new FileOutputStream(file)) {
                    byte[] buffer=new byte[16384];int count;
                    while((count=in.read(buffer))!=-1) out.write(buffer,0,count);
                }
            }
            if (source == null) {
                frame=File.createTempFile("source-",".png",assets);
                try(FileOutputStream out=new FileOutputStream(frame)) {
                    if(!bitmap.compress(Bitmap.CompressFormat.PNG,100,out)) throw new IllegalStateException("opening_png");
                }
                source=frame;
            }
            if (!source.isFile()) throw new IllegalStateException("opening_source_missing");
            String characters;
            try(InputStream in=context.getAssets().open("native-ocr/characters.json")) {
                java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[16384];int count;
                while((count=in.read(buffer))!=-1)bytes.write(buffer,0,count);
                characters=new String(bytes.toByteArray(),StandardCharsets.UTF_8);
            }
            JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native.opening_component")
                .callAttr("inspect_component",source.getAbsolutePath(),assets.getAbsolutePath(),NativeOnnxModels.get(context),characters).toString());
            MulliganRecognizer.Phase phase=MulliganRecognizer.Phase.valueOf(result.getString("phase"));
            JSONArray bounds=result.optJSONArray("target_bounds");Rect target=null;
            if(bounds!=null)target=new Rect(bounds.getInt(0),bounds.getInt(1),bounds.getInt(0)+bounds.getInt(2),bounds.getInt(1)+bounds.getInt(3));
            return new MulliganRecognizer.Result(phase,target,result.getDouble("score"),result.getString("reason"),result.getString("template_id"));
        } catch(Exception error) {
            android.util.Log.e("KardsNativeOpening", "Opening observation failed", error);
            return new MulliganRecognizer.Result(MulliganRecognizer.Phase.UNKNOWN,null,0,
                    "native_opening_error:"+error.getClass().getSimpleName()+":"+error.getMessage(),"");
        } finally {
            if(frame!=null)frame.delete();
        }
    }
}
