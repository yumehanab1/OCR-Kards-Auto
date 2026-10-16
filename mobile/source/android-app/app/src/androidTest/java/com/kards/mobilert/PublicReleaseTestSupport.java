package com.kards.mobilert;

import android.content.Context;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

/** Only the test APK carries these Python sources. No production package is replaced. */
final class PublicReleaseTestSupport {
    private static final String ASSET="public-test-support";
    private static final String[] FIXTURE_ROOTS={"device-tests","native-pipeline-probe","phone-result-probe",
            "phone-inset-probe","aspect-169-probe","dynamic-menu-probe","single-action-tests","native-opening-component"};
    private final Context assets,target;
    private final Path files;
    private final File output;
    private final Set<Path> before;
    private final JSONObject diagnostics=new JSONObject();
    private PyObject bootstrap,state;
    private File directory;

    PublicReleaseTestSupport(Context assets,Context target,File output) throws Exception {
        this.assets=assets;this.target=target;this.output=output;
        files=target.getFilesDir().getCanonicalFile().toPath();before=snapshot();
    }

    JSONObject install() throws Exception {
        directory=Files.createTempDirectory(output.toPath(),"public-python-").toFile();
        byte[] raw;
        try(InputStream input=assets.getAssets().open(ASSET+"/manifest.json")){raw=input.readAllBytes();}
        JSONObject manifest=new JSONObject(new String(raw,StandardCharsets.UTF_8));
        if(manifest.getInt("schema")!=1)throw new IllegalStateException("public_support_manifest_schema");
        JSONArray entries=manifest.getJSONArray("files");Set<String> seen=new HashSet<>();
        for(int index=0;index<entries.length();index++) {
            JSONObject entry=entries.getJSONObject(index);String relative=entry.getString("path");
            if(!allowed(relative) || !seen.add(relative))throw new IllegalStateException("public_support_file_name");
            byte[] data;
            try(InputStream input=assets.getAssets().open(ASSET+"/"+relative)){data=input.readAllBytes();}
            if(data.length!=entry.getLong("bytes") || !sha256(data).equals(entry.getString("sha256")))
                throw new IllegalStateException("public_support_source_hash");
            File destination=new File(directory,relative);
            if(!destination.getCanonicalFile().toPath().startsWith(directory.getCanonicalFile().toPath()))
                throw new IllegalStateException("public_support_outside_directory");
            if(!destination.getParentFile().isDirectory() && !destination.getParentFile().mkdirs())throw new IllegalStateException("public_support_directory");
            Files.write(destination.toPath(),data);
        }
        if(!seen.contains("public_release_test_support.py"))throw new IllegalStateException("public_support_bootstrap_missing");
        Files.write(new File(directory,"manifest.json").toPath(),raw);
        if(!Python.isStarted())Python.start(new AndroidPlatform(target));
        Python python=Python.getInstance();
        bootstrap=python.getModule("runpy").callAttr("run_path",new File(directory,"public_release_test_support.py").getAbsolutePath());
        state=bootstrap.callAttr("get","install").call(directory.getAbsolutePath());
        JSONObject installed=new JSONObject(python.getModule("json").callAttr("dumps",bootstrap.callAttr("get","describe").call(state)).toString());
        diagnostics.put("install",installed).put("manifest_sha256",sha256(raw)).put("source_files",entries.length());
        return diagnostics;
    }

    JSONObject close() {
        JSONArray errors=new JSONArray();int removed=0;
        if(state!=null) {
            try {
                JSONObject restored=new JSONObject(Python.getInstance().getModule("json").callAttr("dumps",
                        bootstrap.callAttr("get","cleanup").call(state)).toString());
                diagnostics.put("python_cleanup",restored);
                if(!restored.optBoolean("passed") || !restored.optBoolean("paths_restored"))errors.put("python_paths_or_origin_not_restored");
            } catch(Throwable failure){errors.put("python_cleanup:"+failure);}
        }
        try {
            List<Path> added=new ArrayList<>(snapshot());added.removeAll(before);
            added.sort(Comparator.comparingInt(Path::getNameCount).reversed());
            for(Path path:added) {
                if(!path.normalize().startsWith(files) || path.equals(files))throw new IllegalStateException("public_cleanup_outside_files");
                if(path.equals(output.toPath().resolve("report.json")))continue;
                Files.delete(path);removed++;
            }
        } catch(Throwable failure){errors.put("fixture_cleanup:"+failure);}
        try {diagnostics.put("removed_new_fixture_paths",removed).put("preserved_existing_paths",before.size())
                .put("errors",errors).put("cleanup_complete",errors.length()==0);}
        catch(Exception ignored){throw new IllegalStateException("public_support_cleanup_report");}
        return diagnostics;
    }

    private Set<Path> snapshot() throws Exception {
        Set<Path> paths=new HashSet<>();
        for(String name:FIXTURE_ROOTS) {
            Path root=files.resolve(name);
            if(!Files.exists(root))continue;
            try(Stream<Path> stream=Files.walk(root)){stream.forEach(paths::add);}
        }
        return paths;
    }

    private static boolean allowed(String name) {
        return name.equals("public_release_test_support.py") || name.matches("(?:apk_native/)?[A-Za-z_][A-Za-z0-9_]*_test\\.py");
    }
    private static String sha256(byte[] data) throws Exception {
        StringBuilder value=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(data))value.append(String.format("%02x",b&255));
        return value.toString();
    }
}
