package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Original OCR model bytes and decoding; never captures or dispatches input. */
final class NativeOriginalOcr {
    static JSONObject inspect(Context context, File png) throws Exception {
        return inspect(context,png,0);
    }
    static JSONObject inspect(Context context, File png, int recognitionHeight) throws Exception {
        String characters;
        try (InputStream in = context.getAssets().open("native-ocr/characters.json")) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[16384]; int count;
            while ((count=in.read(buffer))!=-1) bytes.write(buffer,0,count);
            characters = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
        }
        return new JSONObject(Python.getInstance().getModule("apk_native.onnx_ocr")
                .callAttr("inspect_saved", png.getAbsolutePath(), NativeOnnxModels.get(context), characters, recognitionHeight).toString());
    }
    static JSONObject inspectOpeningRegions(Context context,File png,org.json.JSONArray regions) throws Exception {
        return inspectRegions(context,png,regions,"opening_controls");
    }
    static JSONObject inspectResultRegions(Context context,File png,org.json.JSONArray regions) throws Exception {
        return inspectRegions(context,png,regions,"result_controls");
    }
    static JSONObject inspectMenuRegions(Context context,File png,org.json.JSONArray regions) throws Exception {
        return inspectRegions(context,png,regions,"menu_controls");
    }
    static JSONObject inspectTurnRegions(Context context,File png,org.json.JSONArray regions) throws Exception {
        return inspectRegions(context,png,regions,"turn_controls");
    }
    private static JSONObject inspectRegions(Context context,File png,org.json.JSONArray regions,String scope) throws Exception {
        String characters;
        try(InputStream in=context.getAssets().open("native-ocr/characters.json")) {
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
            byte[] buffer=new byte[16384];int count;
            while((count=in.read(buffer))!=-1)bytes.write(buffer,0,count);
            characters=new String(bytes.toByteArray(),StandardCharsets.UTF_8);
        }
        return new JSONObject(Python.getInstance().getModule("apk_native.onnx_ocr")
            .callAttr("inspect_saved_regions",png.getAbsolutePath(),NativeOnnxModels.get(context),characters,regions.toString(),scope).toString());
    }
}
