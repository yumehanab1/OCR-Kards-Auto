package com.kards.mobilert;

import org.json.JSONArray;

/** Only three bounded current-frame result-label regions are accepted. */
final class ResultOcrRegions {
    static String rejection(String stage, JSONArray regions, int width, int height) {
        if (!"battle".equals(stage)) return "result_ocr_stage_required";
        if (regions.length()!=3) return "result_ocr_region_count";
        try {
            for (int i=0;i<3;i++) {
                JSONArray box=regions.getJSONArray(i);
                if (box.length()!=4) return "result_ocr_region_bounds";
                int x=box.getInt(0),y=box.getInt(1),w=box.getInt(2),h=box.getInt(3);
                if (x<0 || y<0 || w<=0 || h<=0 || x>width-w || y>height-h)
                    return "result_ocr_region_bounds";
                if (i==0 && (x<width*.34 || x+w>width*.66 || y<height*.34 || y+h>height*.85))
                    return "result_ocr_region_bounds";
                if (i==1 && (x<width*.34 || x+w>width*.66 || y<height*.83 || y+h>height*.99))
                    return "result_ocr_region_bounds";
                if (i==2 && (x<width*.74 || y+h>height*.21))
                    return "result_ocr_region_bounds";
            }
        } catch (org.json.JSONException error) { return "result_ocr_region_bounds"; }
        return null;
    }
}
