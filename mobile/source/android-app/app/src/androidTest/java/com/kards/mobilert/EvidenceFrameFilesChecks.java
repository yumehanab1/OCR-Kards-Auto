package com.kards.mobilert;

import android.content.Context;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONObject;

final class EvidenceFrameFilesChecks {
    static JSONObject run(Context context) throws Exception {
        File directory=new File(context.getCacheDir(),"evidence-mirror-"+System.nanoTime());
        if (!directory.mkdirs()) throw new IllegalStateException("mirror_test_directory");
        File original=new File(directory,"original.png"),linked=new File(directory,"round.png"),copied=new File(directory,"copy.png");
        byte[] bytes={1,2,3,4};int checks=0;
        try {
            Files.write(original.toPath(),bytes);
            String mode=EvidenceFrameFiles.mirror(original,linked);
            if (!Arrays.equals(bytes,Files.readAllBytes(linked.toPath()))) throw new IllegalStateException("mirror_bytes");checks++;
            if (!"shared_original_inode".equals(mode) || !Files.isSameFile(original.toPath(),linked.toPath())) throw new IllegalStateException("mirror_inode");checks++;
            if (!"byte_copy".equals(EvidenceFrameFiles.mirror(original,copied,false)) || Files.isSameFile(original.toPath(),copied.toPath())) throw new IllegalStateException("mirror_copy_fallback");checks++;
            boolean rejected=false;
            try {EvidenceFrameFiles.mirror(original,linked);} catch (java.io.IOException expected) {rejected=true;}
            if (!rejected || !Arrays.equals(bytes,Files.readAllBytes(linked.toPath()))) throw new IllegalStateException("mirror_overwrite");checks++;
            Files.delete(original.toPath());
            if (!Arrays.equals(bytes,Files.readAllBytes(linked.toPath()))) throw new IllegalStateException("mirror_survives_unlink");checks++;
            return new JSONObject().put("passed",true).put("checks",checks).put("mode",mode).put("device_inputs",0);
        } finally {
            Files.deleteIfExists(original.toPath());Files.deleteIfExists(linked.toPath());Files.deleteIfExists(copied.toPath());Files.deleteIfExists(directory.toPath());
        }
    }
}
