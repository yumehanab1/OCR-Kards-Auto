package com.kards.mobilert;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import com.google.mlkit.common.sdkinternal.MlKitContext;

/** Some platforms deliver INSTALL_PROVIDER again after early service startup.
 * The bundled stock provider calls non-idempotent zza(); use its public safe API.
 * Component discovery and bundled OCR model initialization are unchanged. */
public final class IdempotentMlKitProvider extends ContentProvider {
    @Override public boolean onCreate() {
        if (getContext() == null) throw new IllegalStateException("mlkit_provider_context_missing");
        MlKitContext.initializeIfNeeded(getContext());
        android.util.Log.d("KardsMlKit", "provider_initialized pid=" + android.os.Process.myPid());
        return true;
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String selection, String[] args) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { return 0; }
}
