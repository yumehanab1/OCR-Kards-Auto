package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Host-runnable release policy and HTTP ownership regression checks. No network. */
public final class UpdateCheckerChecks {
    public static void run() throws Exception {
        require(!UpdateChecker.newerNumericVersion("v0.2.3", "0.2.4"));
        require(!UpdateChecker.newerNumericVersion("v0.2.4", "0.2.4"));
        require(UpdateChecker.newerNumericVersion("v0.2.10", "0.2.9"));
        require(UpdateChecker.newerNumericVersion("1.0.0", "0.99.999"));
        for (String version : new String[]{"", "v0.3.0-dev", "0.3", "release-2.0.0", "0.x.9"}) {
            require(!UpdateChecker.newerNumericVersion(version, "0.2.4"));
            require(!UpdateChecker.newerNumericVersion("9.0.0", version));
        }
        JSONObject release = new JSONObject().put("tag_name", "v0.2.4").put("body", "versionCode: 191")
                .put("assets", new JSONArray().put(new JSONObject().put("name", "mobile.APK")
                        .put("browser_download_url", "https://example.test/mobile.apk")));
        require(UpdateChecker.parseRelease(release, 190, "99.0.0").available);
        require(!UpdateChecker.parseRelease(release, 191, "0.1.0").available);
        require(!UpdateChecker.parseRelease(release, 192, "0.1.0").available);
        release.put("body", "").put("tag_name", "v0.2.3");
        require(!UpdateChecker.parseRelease(release, 190, "0.2.4").available);
        release.put("tag_name", "v0.2.5");
        require(UpdateChecker.parseRelease(release, 190, "0.2.4").available);
        release.getJSONArray("assets").getJSONObject(0).put("browser_download_url", JSONObject.NULL);
        require(!UpdateChecker.parseRelease(release, 190, "0.2.4").available);
        release.put("assets", new JSONArray()).put("body", "versionCode: 999");
        require(!UpdateChecker.parseRelease(release, 190, "0.2.4").available);
        for (int status : new int[]{200, 404, 500}) {
            FakeConnection connection = new FakeConnection(status, false, false);
            try {
                require(UpdateChecker.readResponse(connection, "0.2.4").contains("payload"));
                require(status == 200);
            } catch (IOException expected) { require(status != 200); }
            require(connection.closed && connection.disconnected);
        }
        for (boolean responseFailure : new boolean[]{false, true}) {
            FakeConnection connection = new FakeConnection(200, true, responseFailure);
            try { UpdateChecker.readResponse(connection, "0.2.4"); throw new AssertionError("Expected failure"); }
            catch (IOException expected) { }
            require(connection.disconnected && (responseFailure || connection.closed));
        }
        FakeConnection missingError = new FakeConnection(403, false, false);
        missingError.noErrorStream = true;
        try { UpdateChecker.readResponse(missingError, "0.2.4"); throw new AssertionError(); }
        catch (IOException expected) { require(missingError.disconnected); }
    }

    private static final class FakeConnection extends HttpURLConnection {
        final boolean readFailure, responseFailure;
        boolean closed, disconnected, noErrorStream;
        FakeConnection(int status, boolean readFailure, boolean responseFailure) throws Exception {
            super(new URL("https://example.test/release"));
            responseCode = status;
            this.readFailure = readFailure;
            this.responseFailure = responseFailure;
        }
        @Override public int getResponseCode() throws IOException {
            if (responseFailure) throw new IOException("response failed");
            return responseCode;
        }
        private InputStream stream() {
            ByteArrayInputStream data = new ByteArrayInputStream("payload".getBytes(StandardCharsets.UTF_8));
            return new InputStream() {
                @Override public int read() throws IOException {
                    if (readFailure) throw new IOException("read failed");
                    return data.read();
                }
                @Override public void close() { closed = true; }
            };
        }
        @Override public InputStream getInputStream() { return stream(); }
        @Override public InputStream getErrorStream() { return noErrorStream ? null : stream(); }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() { }
    }
    private static void require(boolean value) { if (!value) throw new AssertionError("update regression"); }
}
