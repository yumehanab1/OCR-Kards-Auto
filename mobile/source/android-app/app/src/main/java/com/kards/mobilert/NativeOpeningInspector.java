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
import java.io.IOException;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;

/** No inputs: the bounded session retains freshness, pairing and foreground gates. */
final class NativeOpeningInspector implements BoundedMulliganSession.Inspector {
    private final Context context;
    private final String buildIdentity;
    NativeOpeningInspector(Context context) {
        this.context=context.getApplicationContext();
        String identity;
        try {
            android.content.pm.PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            identity = info.getLongVersionCode() + "-" + info.lastUpdateTime;
        } catch (Exception unavailable) {
            // Never reuse an unverifiable install across inspector lifetimes.
            identity = "unknown-" + UUID.randomUUID();
        }
        buildIdentity = identity;
    }
    File assetDirectory() {
        return new File(new File(context.getFilesDir(), "native-opening-component"), buildIdentity);
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
            File assets = installAssets(new File(context.getFilesDir(), "native-opening-component"),
                    buildIdentity, context.getAssets().list("mulligan-one-shot"),
                    name -> context.getAssets().open("mulligan-one-shot/" + name));
            if (source == null) {
                frame=File.createTempFile("source-",".png",assets);
                try(FileOutputStream out=new FileOutputStream(frame)) {
                    OriginalPng.write(bitmap,out);
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

    interface AssetOpener { InputStream open(String name) throws IOException; }

    /** Same-volume staging: a failed copy can never look like a completed installation. */
    static synchronized File installAssets(File root, String identity, String[] names, AssetOpener opener)
            throws IOException {
        if (!identity.matches("[A-Za-z0-9-]+") || names == null || names.length == 0)
            throw new IOException("opening_assets_manifest");
        File target = new File(root, identity);
        File marker = new File(target, ".complete");
        if (marker.isFile() && identity.equals(new String(Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8)))
            return target;
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("opening_assets_directory");
        removeIncomplete(target);
        File staging = new File(root, identity + ".install");
        removeIncomplete(staging);
        if (!staging.mkdir()) throw new IOException("opening_assets_staging");
        try {
            for (String name : names) {
                if (name.isEmpty() || name.equals(".complete") || !new File(name).getName().equals(name)
                        || name.equals(".") || name.equals("..")) throw new IOException("opening_asset_name");
                try (InputStream in = opener.open(name)) { installFile(staging, name, in); }
            }
            installFile(staging, ".complete", new ByteArrayInputStream(identity.getBytes(StandardCharsets.UTF_8)));
            if (!staging.renameTo(target)) throw new IOException("opening_assets_publish");
            return target;
        } finally {
            removeIncomplete(staging);
        }
    }

    private static void installFile(File directory, String name, InputStream in) throws IOException {
        File temporary = File.createTempFile("asset-", ".tmp", directory);
        try {
            try (FileOutputStream out = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[16384];
                int count;
                while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
                out.flush();
                out.getFD().sync();
            }
            if (!temporary.renameTo(new File(directory, name))) throw new IOException("opening_asset_publish");
        } finally {
            if (temporary.exists() && !temporary.delete()) throw new IOException("opening_asset_cleanup");
        }
    }

    private static void removeIncomplete(File file) throws IOException {
        if (!file.exists()) return;
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children == null) throw new IOException("opening_assets_list");
            for (File child : children) removeIncomplete(child);
        }
        if (!file.delete()) throw new IOException("opening_assets_cleanup");
    }
}
