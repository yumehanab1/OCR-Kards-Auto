package com.kards.mobilert;

import android.graphics.Bitmap;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

/** Exact source pixels, low compression. Avoid slow adaptive PNG filters before dispatch. */
final class OriginalPng {
    private OriginalPng() { }
    static void write(Bitmap bitmap, OutputStream destination) throws IOException {
        if(bitmap==null || bitmap.isRecycled()) throw new IOException("png_bitmap_missing");
        int width=bitmap.getWidth(),height=bitmap.getHeight();
        if(width<=0 || height<=0 || width>16384 || height>16384) throw new IOException("png_geometry");
        DataOutputStream output=new DataOutputStream(new BufferedOutputStream(destination,65536));
        output.writeLong(0x89504E470D0A1A0AL);
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(13);
        DataOutputStream header=new DataOutputStream(bytes);
        header.writeInt(width);header.writeInt(height);header.writeByte(8);header.writeByte(6);
        header.writeByte(0);header.writeByte(0);header.writeByte(0);
        chunk(output,"IHDR",bytes.toByteArray(),13);
        Deflater deflater=new Deflater(Deflater.BEST_SPEED);
        byte[] compressed=new byte[65536],row=new byte[width*4+1];
        int stripHeight=Math.min(64,height);int[] pixels=new int[width*stripHeight];
        try {
            for(int top=0;top<height;top+=stripHeight) {
                int count=Math.min(stripHeight,height-top);
                bitmap.getPixels(pixels,0,width,0,top,width,count);
                for(int y=0;y<count;y++) {
                    row[0]=0;
                    for(int x=0,p=1;x<width;x++) {
                        int color=pixels[y*width+x];
                        row[p++]=(byte)(color>>>16);row[p++]=(byte)(color>>>8);
                        row[p++]=(byte)color;row[p++]=(byte)(color>>>24);
                    }
                    deflater.setInput(row);
                    while(!deflater.needsInput()) {
                        int size=deflater.deflate(compressed);
                        if(size>0)chunk(output,"IDAT",compressed,size);
                    }
                }
            }
            deflater.finish();
            while(!deflater.finished()) {
                int size=deflater.deflate(compressed);
                if(size<=0)throw new IOException("png_compressor_stalled");
                chunk(output,"IDAT",compressed,size);
            }
            chunk(output,"IEND",new byte[0],0);output.flush();
        } finally { deflater.end(); }
    }
    private static void chunk(DataOutputStream output,String name,byte[] data,int length) throws IOException {
        byte[] type=name.getBytes(StandardCharsets.US_ASCII);
        CRC32 crc=new CRC32();crc.update(type);crc.update(data,0,length);
        output.writeInt(length);output.write(type);output.write(data,0,length);output.writeInt((int)crc.getValue());
    }
}
