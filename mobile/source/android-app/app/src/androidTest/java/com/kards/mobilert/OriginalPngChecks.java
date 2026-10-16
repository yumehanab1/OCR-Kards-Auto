package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.SystemClock;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.util.Arrays;

final class OriginalPngChecks {
    static JSONObject run() throws Exception {
        Bitmap small=Bitmap.createBitmap(13,11,Bitmap.Config.ARGB_8888);
        int[] pixels=new int[143];int[] colors={0x00000000,0x80FF3366,0x010000FF,0xFFFFFFFF,0xFF010203};
        for(int i=0;i<pixels.length;i++)pixels[i]=colors[i%colors.length];
        small.setPixels(pixels,0,13,0,0,13,11);verify(small);small.recycle();
        Bitmap source=Bitmap.createBitmap(2780,1264,Bitmap.Config.ARGB_8888);
        int[] row=new int[2780];
        for(int y=0;y<1264;y++) {
            for(int x=0;x<2780;x++)row[x]=0xFF000000|(((x*13+y*7)&255)<<16)|(((x*5+y*19)&255)<<8)|((x*31+y*3)&255);
            source.setPixels(row,0,2780,0,y,2780,1);
        }
        long started=SystemClock.elapsedRealtime();byte[] fast=verify(source);
        long fastMs=SystemClock.elapsedRealtime()-started;
        ByteArrayOutputStream nativeBytes=new ByteArrayOutputStream();started=SystemClock.elapsedRealtime();
        if(!source.compress(Bitmap.CompressFormat.PNG,100,nativeBytes))throw new IllegalStateException("builtin_png");
        long builtinMs=SystemClock.elapsedRealtime()-started;
        Bitmap nativeDecoded=BitmapFactory.decodeByteArray(nativeBytes.toByteArray(),0,nativeBytes.size());
        Bitmap fastDecoded=BitmapFactory.decodeByteArray(fast,0,fast.length);
        compare(nativeDecoded,fastDecoded);source.recycle();nativeDecoded.recycle();fastDecoded.recycle();
        return new JSONObject().put("passed",true).put("alpha_and_opaque_pixels_exact",true)
            .put("phone_size_pixels_exact",true).put("width",2780).put("height",1264)
            .put("fast_encode_decode_check_ms",fastMs).put("builtin_encode_ms",builtinMs)
            .put("fast_bytes",fast.length).put("builtin_bytes",nativeBytes.size()).put("device_inputs",0);
    }
    private static byte[] verify(Bitmap source) throws Exception {
        ByteArrayOutputStream output=new ByteArrayOutputStream();OriginalPng.write(source,output);
        byte[] raw=output.toByteArray();Bitmap decoded=BitmapFactory.decodeByteArray(raw,0,raw.length);
        compare(source,decoded);decoded.recycle();return raw;
    }
    private static void compare(Bitmap a,Bitmap b) {
        if(b==null || a.getWidth()!=b.getWidth() || a.getHeight()!=b.getHeight())throw new IllegalStateException("png_shape");
        int w=a.getWidth(),h=a.getHeight();int[] one=new int[w],two=new int[w];
        for(int y=0;y<h;y++) {
            a.getPixels(one,0,w,0,y,w,1);b.getPixels(two,0,w,0,y,w,1);
            if(!Arrays.equals(one,two))throw new IllegalStateException("png_pixel_row:"+y);
        }
    }
}
