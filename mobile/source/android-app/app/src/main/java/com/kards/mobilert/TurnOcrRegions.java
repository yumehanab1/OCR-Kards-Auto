package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONException;

/** A single bounded right-side turn-control OCR region; never a tap target. */
final class TurnOcrRegions {
    static String rejection(String stage, JSONArray regions, int width, int height) {
        if (!"battle".equals(stage)) return "turn_ocr_stage_required";
        if (regions==null || regions.length()!=1) return "turn_ocr_region_count";
        if (width<=0 || height<=0) return "turn_ocr_region_bounds";
        try {
            JSONArray box=regions.getJSONArray(0);
            if (box.length()!=4) return "turn_ocr_region_bounds";
            int[] values=new int[4];
            for (int i=0;i<4;i++) {
                Object value=box.get(i);
                if (!(value instanceof Number)) return "turn_ocr_region_bounds";
                double number=((Number)value).doubleValue();
                if (!Double.isFinite(number) || number!=Math.rint(number)
                        || number<Integer.MIN_VALUE || number>Integer.MAX_VALUE)
                    return "turn_ocr_region_bounds";
                values[i]=(int)number;
            }
            int x=values[0],y=values[1],w=values[2],h=values[3];
            if (x<0 || y<0 || w<=0 || h<=0 || x>width-w || y>height-h
                    || x<width*.59 || y<height*.30 || y+h>height*.94)
                return "turn_ocr_region_bounds";
        } catch (JSONException error) { return "turn_ocr_region_bounds"; }
        return null;
    }
}
