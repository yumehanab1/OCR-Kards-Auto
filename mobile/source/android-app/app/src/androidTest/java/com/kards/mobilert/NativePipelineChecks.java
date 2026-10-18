package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Full source-pixel observation on saved images, without capture or input. */
final class NativePipelineChecks {
    static void copy(Context context, String asset, File destination) throws Exception {
        String[] children=context.getAssets().list(asset);
        if (children!=null && children.length>0) {
            if (!destination.isDirectory() && !destination.mkdirs()) throw new IOException("native_fixture_directory");
            for (String name:children) copy(context,asset+"/"+name,new File(destination,name));
        } else {
            try (InputStream input=context.getAssets().open(asset);FileOutputStream output=new FileOutputStream(destination)) {
                TestStreams.copy(input, output);
            }
        }
    }
    static JSONObject run(Context test, Context target) throws Exception {
        File directory=new File(target.getFilesDir(),"native-pipeline-probe");
        copy(test,"native-pipeline-probe",directory);
        JSONArray manifest=new JSONArray(new String(java.nio.file.Files.readAllBytes(new File(directory,"manifest.json").toPath()),StandardCharsets.UTF_8));
        for (int i=0;i<manifest.length();i++) {
            JSONObject item=manifest.getJSONObject(i);
            byte[] bytes=java.nio.file.Files.readAllBytes(new File(directory,item.getString("file")).toPath());
            StringBuilder digest=new StringBuilder();
            for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes)) digest.append(String.format("%02x",b&255));
            if(!digest.toString().equals(item.getString("sha256"))) throw new IllegalStateException("native_fixture_hash");
        }
        File core=new File(directory,"core"),menu=new File(directory,"menu"),opening=new File(directory,"opening");
        copy(target,"mobile-core",core);copy(target,"match-entry",menu);copy(target,"mulligan-one-shot",opening);
        String characters;
        try(InputStream input=target.getAssets().open("native-ocr/characters.json")) {
            characters=new String(TestStreams.readAll(input),StandardCharsets.UTF_8);
        }
        if(!Python.isStarted()) Python.start(new AndroidPlatform(target));
        JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native_bootstrap")
            .callAttr("saved_pipeline",directory.getAbsolutePath(),core.getAbsolutePath(),menu.getAbsolutePath(),
                opening.getAbsolutePath(),NativeOnnxModels.get(target),characters).toString());
        if(result.getJSONArray("frames").length()!=manifest.length()) throw new IllegalStateException("native_fixture_missing_output");
        JSONArray menus = result.getJSONArray("native_menu_frames");
        int expectedMenus=0;
        for(int i=0;i<manifest.length();i++) {
            JSONObject item=manifest.getJSONObject(i);String state=item.getString("expected_state");
            if(item.has("expected_menu_state") || "home".equals(state) || "deck_menu".equals(state) || "deck_detail".equals(state)) expectedMenus++;
        }
        if (menus.length()!=expectedMenus) throw new IllegalStateException("native_menu_fixture_missing");
        for (int i=0;i<menus.length();i++) if (!menus.getJSONObject(i).getBoolean("passed"))
            throw new IllegalStateException("native_menu_fixture_state:"+menus.getJSONObject(i).getString("file"));
        JSONArray frames=result.getJSONArray("frames");
        for (int i=0;i<frames.length();i++) {
            JSONObject item=frames.getJSONObject(i);
            if ("result_defeat".equals(item.optString("expected_state"))
                    && !item.getJSONObject("page").getJSONObject("result_proof").optBoolean("ready"))
                throw new IllegalStateException("native_result_proof_missing");
        }
        android.graphics.Bitmap bitmap=android.graphics.BitmapFactory.decodeFile(new File(directory,"frame-00.png").getAbsolutePath());
        NativeOpeningInspector inspector=new NativeOpeningInspector(target);
        for(int i=0;i<manifest.length();i++){
            JSONObject item=manifest.getJSONObject(i);
            if(!item.has("expected_opening_phase"))continue;
            File source=new File(directory,item.getString("file"));
            android.graphics.Bitmap saved=android.graphics.BitmapFactory.decodeFile(source.getAbsolutePath());
            try {
                MulliganRecognizer.Result observed=inspector.inspectSaved(saved,source);
                if(!item.getString("expected_opening_phase").equals(observed.phase.name()))
                    throw new IllegalStateException("saved_opening_phase:"+observed.phase+":"+observed.reason);
                result.put("opponent_first_opening_phase",observed.phase.name());
            } finally {saved.recycle();}
        }
        JSONArray times=new JSONArray();
        try {
            for(int i=0;i<3;i++) {
                long started=android.os.SystemClock.elapsedRealtime();
                MulliganRecognizer.Result openingResult=inspector.inspect(bitmap);
                long elapsed=android.os.SystemClock.elapsedRealtime()-started;
                times.put(elapsed);
                if(openingResult.phase!=MulliganRecognizer.Phase.MULLIGAN_CONFIRM)
                    throw new IllegalStateException("native_opening_saved_unconfirmed:"+openingResult.reason);
                if(i>0 && elapsed>=1500) throw new IllegalStateException("native_opening_saved_age_budget:"+elapsed);
            }
        } finally {bitmap.recycle();}
        result.put("native_opening_saved_ms",times);
        File fullSource = new File(directory,"live-opening-2772.png");
        android.graphics.Bitmap fullBitmap=android.graphics.BitmapFactory.decodeFile(fullSource.getAbsolutePath());
        JSONArray fullTimes=new JSONArray();
        try {
            for(int i=0;i<3;i++) {
                long started=android.os.SystemClock.elapsedRealtime();
                File persisted=new File(directory,"opening-source-persisted.png");
                try(FileOutputStream stream=new FileOutputStream(persisted)) {
                    if(!fullBitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,stream)) throw new IOException("fixture_png");
                    stream.flush();stream.getFD().sync();
                }
                long persistedAt=android.os.SystemClock.elapsedRealtime();
                MulliganRecognizer.Result observed=inspector.inspectSaved(fullBitmap,persisted);
                long finished=android.os.SystemClock.elapsedRealtime();
                fullTimes.put(new JSONObject().put("persist_ms",persistedAt-started)
                    .put("inspect_ms",finished-persistedAt).put("total_ms",finished-started));
                if(observed.phase!=MulliganRecognizer.Phase.MULLIGAN_CONFIRM) throw new IllegalStateException("full_source_opening_unknown");
                if(finished-started>=5000) throw new IllegalStateException("full_source_opening_age:"+fullTimes);
            }
        } finally {fullBitmap.recycle();}
        result.put("native_opening_full_source_ms",fullTimes);
        android.graphics.Bitmap ownBitmap=android.graphics.BitmapFactory.decodeFile(new File(directory,"live-own-2772.png").getAbsolutePath());
        JSONArray ownTimes=new JSONArray();
        try {
            for(int i=0;i<3;i++) {
                long started=android.os.SystemClock.elapsedRealtime();
                File source=new File(directory,"own-persisted.png");
                try(FileOutputStream stream=new FileOutputStream(source)) {
                    ownBitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,stream);stream.flush();stream.getFD().sync();
                }
                MulliganRecognizer.Result observed=inspector.inspectSaved(ownBitmap,source);
                long elapsed=android.os.SystemClock.elapsedRealtime()-started;ownTimes.put(elapsed);
                if(observed.phase!=MulliganRecognizer.Phase.CONFIRMED_MY_TURN || elapsed>=5000)
                    throw new IllegalStateException("source_own_control_budget:"+observed.reason+":"+elapsed);
            }
        } finally {ownBitmap.recycle();}
        result.put("native_opening_own_source_ms",ownTimes);
        JSONObject daily=new JSONObject(Python.getInstance().getModule("apk_native.login_popup")
            .callAttr("saved_check",new File(directory,"daily-popup-2772.png").getAbsolutePath(),menu.getAbsolutePath()).toString());
        if(!daily.getBoolean("passed")) throw new IllegalStateException("daily_popup_saved");
        result.put("native_daily_popup",daily);
        return result;
    }
}
