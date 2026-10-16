package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import org.json.JSONObject;

/** Already saved phone review, without any game capture or input. */
final class PhoneInsetChecks {
    static JSONObject run(Context test, Context target) throws Exception {
        File directory=new File(target.getFilesDir(),"phone-inset-probe");
        NativePipelineChecks.copy(test,"phone-inset-probe",directory);
        File opening=new File(directory,"opening");
        NativePipelineChecks.copy(target,"mulligan-one-shot",opening);
        File menu=new File(directory,"menu");
        NativePipelineChecks.copy(target,"match-entry",menu);
        if(!Python.isStarted()) Python.start(new AndroidPlatform(target));
        JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native.resource_anchors_test")
            .callAttr("run",new File(directory,"phone114-battle-review.jpg").getAbsolutePath(),opening.getAbsolutePath()).toString());
        result.put("phone_menu",new JSONObject(Python.getInstance().getModule("apk_native.phone_menu_test")
            .callAttr("run",new File(directory,"phone114-menu-review.jpg").getAbsolutePath(),menu.getAbsolutePath()).toString()));
        result.put("phone_settle",new JSONObject(Python.getInstance().getModule("apk_native.phone_settle_test")
            .callAttr("run",new File(directory,"phone121-settle-review.jpg").getAbsolutePath(),menu.getAbsolutePath(),
                      new File(directory,"phone114-menu-review.jpg").getAbsolutePath()).toString()));
        String characters;
        try(java.io.InputStream in=target.getAssets().open("native-ocr/characters.json")) {
            characters=new String(in.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        }
        result.put("phone_mulligan",new JSONObject(Python.getInstance().getModule("apk_native.phone_mulligan_test")
            .callAttr("run_device",new File(directory,"phone116-mulligan-review.jpg").getAbsolutePath(),opening.getAbsolutePath(),
                      NativeOnnxModels.get(target),characters).toString()));
        return result;
    }
}
