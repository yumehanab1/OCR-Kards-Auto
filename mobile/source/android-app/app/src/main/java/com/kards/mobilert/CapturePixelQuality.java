package com.kards.mobilert;

import android.graphics.Bitmap;

/** Pixel checks before a capture can become game evidence. */
final class CapturePixelQuality {
    private CapturePixelQuality() { }

    /** Final MediaProjection output must cover the canvas with fully opaque pixels. */
    static boolean isFullyOpaque(Bitmap bitmap) {
        if(bitmap==null || bitmap.isRecycled())throw new IllegalArgumentException("capture_bitmap_missing");
        int width=bitmap.getWidth(),height=bitmap.getHeight();
        int rows=Math.min(32,height);int[] pixels=new int[width*rows];
        for(int top=0;top<height;top+=rows){
            int count=Math.min(rows,height-top);
            bitmap.getPixels(pixels,0,width,0,top,width,count);
            for(int i=0;i<width*count;i++)if((pixels[i]>>>24)!=255)return false;
        }
        return true;
    }

    /** A single nonblack pixel protects sparse loading text from rejection. */
    static boolean isAllBlack(Bitmap bitmap) {
        if(bitmap==null || bitmap.isRecycled())throw new IllegalArgumentException("capture_bitmap_missing");
        int width=bitmap.getWidth(),height=bitmap.getHeight();
        // Healthy frames normally finish here without allocating a full-frame pixel array.
        for(int y=0;y<height;y+=Math.max(1,height/12))
            for(int x=0;x<width;x+=Math.max(1,width/16))
                if((bitmap.getPixel(x,y)&0xffffff)!=0)return false;
        // Confirm every pixel before rejecting; sparse text on a black loading page is valid.
        int rows=Math.min(32,height);int[] pixels=new int[width*rows];
        for(int top=0;top<height;top+=rows){
            int count=Math.min(rows,height-top);
            bitmap.getPixels(pixels,0,width,0,top,width,count);
            for(int i=0;i<width*count;i++)if((pixels[i]&0xffffff)!=0)return false;
        }
        return true;
    }
}
