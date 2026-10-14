package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.File;

/** Saved references and labelled generated cases; never captures or dispatches. */
final class SpecialSkinsChecks {
    static JSONObject run(Context test,Context target) throws Exception {
        File directory=new File(target.getFilesDir(),"special-skins-probe");
        NativePipelineChecks.copy(test,"special-skins-probe",directory);
        File core=new File(directory,"core"),menu=new File(directory,"menu"),opening=new File(directory,"opening");
        NativePipelineChecks.copy(target,"mobile-core",core);
        NativePipelineChecks.copy(target,"match-entry",menu);
        NativePipelineChecks.copy(target,"mulligan-one-shot",opening);
        if(!Python.isStarted())Python.start(new AndroidPlatform(target));
        JSONObject result=new JSONObject(Python.getInstance().getModule("apk_native_bootstrap")
                .callAttr("special_skins_replay",directory.getAbsolutePath(),core.getAbsolutePath(),
                        menu.getAbsolutePath(),opening.getAbsolutePath()).toString());
        if(!result.optBoolean("passed") || result.optInt("fixture_count")!=268)
            throw new IllegalStateException("special_skins_replay_failed:"+result.optJSONArray("failures"));
        return result;
    }
}
