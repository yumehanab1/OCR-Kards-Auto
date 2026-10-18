package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Color;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import org.json.JSONObject;

final class CapturePixelQualityChecks {
    static JSONObject run() throws Exception {
        Bitmap bitmap=Bitmap.createBitmap(1280,720,Bitmap.Config.ARGB_8888);
        try {
            bitmap.eraseColor(Color.BLACK);
            require(CapturePixelQuality.isAllBlack(bitmap),"opaque black must reject");
            // Off-grid, bottom-right pixels protect sparse loading text from false rejection.
            bitmap.setPixel(1279,719,Color.rgb(1,0,0));
            require(!CapturePixelQuality.isAllBlack(bitmap),"single off-grid pixel must survive");
            bitmap.eraseColor(Color.BLACK);bitmap.setPixel(17,35,Color.WHITE);
            require(!CapturePixelQuality.isAllBlack(bitmap),"sparse glyph must survive");
            bitmap.eraseColor(Color.TRANSPARENT);
            require(CapturePixelQuality.isAllBlack(bitmap),"empty transparent frame must reject");
            Bitmap tiny=Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888);
            try {tiny.eraseColor(Color.BLACK);require(CapturePixelQuality.isAllBlack(tiny),"tiny black");
                tiny.setPixel(0,0,Color.BLUE);require(!CapturePixelQuality.isAllBlack(tiny),"tiny visible");}
            finally{tiny.recycle();}
            bitmap.eraseColor(Color.rgb(4,8,12));
            require(CapturePixelQuality.isFullyOpaque(bitmap),"fully opaque projection must survive");
            bitmap.setPixel(1279,719,Color.TRANSPARENT);
            require(!CapturePixelQuality.isFullyOpaque(bitmap),"single transparent pixel must reject");
            bitmap.eraseColor(Color.WHITE);bitmap.setPixel(17,35,Color.argb(128,100,80,60));
            require(!CapturePixelQuality.isFullyOpaque(bitmap),"semi-transparent pixel must reject");
            String raw="{\"active\":false,\"event\":\"finished\",\"session_id\":\"capture-test\",\"reason\":\"menu_entry_failed:capture_black_frame\"}";
            require(TrainingPanelState.from(raw).stopReason.contains("兼容截图"),"specific black capture explanation");
            String retry="{\"active\":true,\"event\":\"capture_retry\",\"reason\":\"capture_black_frame\"}";
            require(FloatingStatus.from(retry,"").phase.contains("截图黑屏"),"specific retry label");
            int rgbaChecks=checkRgbaCopy();
            return new JSONObject().put("passed",true).put("checks",11+rgbaChecks)
                    .put("rgba_copy_checks",rgbaChecks).put("device_inputs",0);
        } finally {bitmap.recycle();}
    }

    private static int checkRgbaCopy() {
        int[] colors={Color.RED,Color.GREEN,Color.BLUE,Color.WHITE};
        assertCopy(rgbaBytes(0,3,1,4,12,Color.RED,Color.GREEN,Color.BLUE),
                3,1,4,12,new int[]{Color.RED,Color.GREEN,Color.BLUE},"packed RGBA colors");
        Bitmap transparent=CompatCaptureSource.copyRgbaPixels(
                rgbaBytes(0,1,1,4,4,Color.TRANSPARENT),1,1,4,4);
        try {require(Color.alpha(transparent.getPixel(0,0))==0
                && !CapturePixelQuality.isFullyOpaque(transparent),"zero alpha must remain rejectable");}
        finally {transparent.recycle();}
        Bitmap translucent=CompatCaptureSource.copyRgbaPixels(
                rgbaBytes(0,1,1,4,4,Color.argb(128,0,0,0)),1,1,4,4);
        try {require(Color.alpha(translucent.getPixel(0,0))==128
                && !CapturePixelQuality.isFullyOpaque(translucent),"partial alpha must remain rejectable");}
        finally {translucent.recycle();}
        // The last row contains only visible bytes, with no trailing row padding.
        assertCopy(rgbaBytes(0,2,2,4,12,colors),2,2,4,12,colors,"padded short final row");
        ByteBuffer offset=rgbaBytes(3,2,2,4,12,colors).order(ByteOrder.LITTLE_ENDIAN);
        int position=offset.position(),limit=offset.limit();ByteOrder order=offset.order();
        offset.mark();
        assertCopy(offset,2,2,4,12,colors,"nonzero source position");
        offset.reset();
        require(offset.position()==position && offset.limit()==limit && offset.order()==order,
                "source position, limit, mark and order must remain unchanged");
        assertCopy(rgbaBytes(0,2,2,8,20,colors),2,2,8,20,colors,"unusual pixel stride fallback");
        ByteBuffer shortLast=rgbaBytes(0,2,2,4,12,colors);shortLast.limit(shortLast.limit()-1);
        expectInvalid(shortLast,2,2,4,12,"truncated last pixel");
        expectInvalid(ByteBuffer.allocate(16),2,2,4,4,"short row stride");
        expectInvalid(ByteBuffer.allocate(16),2,2,3,8,"short pixel stride");
        expectInvalid(ByteBuffer.allocate(4),0,1,4,4,"zero width");
        expectInvalid(ByteBuffer.allocate(4),1,0,4,4,"zero height");
        expectInvalid(ByteBuffer.allocate(4),Integer.MAX_VALUE,2,4,Integer.MAX_VALUE,"oversized dimensions");
        expectInvalid(null,1,1,4,4,"missing buffer");
        return 14;
    }

    private static ByteBuffer rgbaBytes(int prefix,int width,int height,int pixelStride,
                                        int rowStride,int... colors) {
        ByteBuffer bytes=ByteBuffer.allocate(prefix+(height-1)*rowStride+(width-1)*pixelStride+4);
        for(int y=0;y<height;y++)for(int x=0;x<width;x++) {
            int color=colors[y*width+x],at=prefix+y*rowStride+x*pixelStride;
            bytes.put(at,(byte)Color.red(color));bytes.put(at+1,(byte)Color.green(color));
            bytes.put(at+2,(byte)Color.blue(color));bytes.put(at+3,(byte)Color.alpha(color));
        }
        bytes.position(prefix);
        return bytes;
    }

    private static void assertCopy(ByteBuffer bytes,int width,int height,int pixelStride,
                                   int rowStride,int[] expected,String message) {
        Bitmap bitmap=CompatCaptureSource.copyRgbaPixels(bytes,width,height,pixelStride,rowStride);
        try {
            for(int y=0;y<height;y++)for(int x=0;x<width;x++)
                require(bitmap.getPixel(x,y)==expected[y*width+x],message+" at "+x+","+y);
        } finally {bitmap.recycle();}
    }

    private static void expectInvalid(ByteBuffer bytes,int width,int height,int pixelStride,
                                      int rowStride,String message) {
        try {
            Bitmap unexpected=CompatCaptureSource.copyRgbaPixels(bytes,width,height,pixelStride,rowStride);
            unexpected.recycle();
        } catch(IllegalArgumentException expected) {return;}
        throw new IllegalStateException(message+" must reject");
    }
    private static void require(boolean condition,String message){if(!condition)throw new IllegalStateException(message);}
}
