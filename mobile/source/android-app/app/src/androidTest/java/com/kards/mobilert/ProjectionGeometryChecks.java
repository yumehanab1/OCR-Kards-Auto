package com.kards.mobilert;

import android.graphics.Bitmap;

/** Natural output buffers are quarter-turned whole, with no scale/crop/alpha repair. */
final class ProjectionGeometryChecks {
    static int run() {
        require(ProjectionGeometry.bufferWidth(1612, 720, 0) == 1612
                && ProjectionGeometry.bufferHeight(1612, 720, 0) == 720, "rotation0");
        require(ProjectionGeometry.bufferWidth(1612, 720, 1) == 720
                && ProjectionGeometry.bufferHeight(1612, 720, 1) == 1612, "rotation90");
        require(ProjectionGeometry.bufferWidth(1612, 720, 2) == 1612
                && ProjectionGeometry.bufferHeight(1612, 720, 2) == 720, "rotation180");
        require(ProjectionGeometry.bufferWidth(1612, 720, 3) == 720
                && ProjectionGeometry.bufferHeight(1612, 720, 3) == 1612, "rotation270");
        require(!ProjectionGeometry.swapsAxes(0) && !ProjectionGeometry.swapsAxes(2), "fixed axes");
        require(ProjectionGeometry.swapsAxes(1) && ProjectionGeometry.swapsAxes(3), "swapped axes");
        for (int rotation : new int[]{-1, 4}) {
            boolean rejected = false;
            try { ProjectionGeometry.swapsAxes(rotation); } catch (IllegalArgumentException expected) { rejected = true; }
            require(rejected, "invalid rotation");
        }
        int[] pixels = {0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffff00, 0xff00ffff, 0xffff00ff};
        int[][] expected = {pixels, {pixels[1], pixels[3], pixels[5], pixels[0], pixels[2], pixels[4]},
                {pixels[5], pixels[4], pixels[3], pixels[2], pixels[1], pixels[0]},
                {pixels[4], pixels[2], pixels[0], pixels[5], pixels[3], pixels[1]}};
        Bitmap source = Bitmap.createBitmap(pixels, 2, 3, Bitmap.Config.ARGB_8888);
        try {
            for (int rotation = 0; rotation < 4; rotation++) {
                Bitmap result = ProjectionGeometry.toLogical(source, rotation);
                try {
                    require(result.getWidth() == (rotation % 2 == 0 ? 2 : 3)
                            && result.getHeight() == (rotation % 2 == 0 ? 3 : 2), "whole frame dimensions");
                    int[] actual = new int[6];
                    result.getPixels(actual, 0, result.getWidth(), 0, 0, result.getWidth(), result.getHeight());
                    require(java.util.Arrays.equals(actual, expected[rotation]), "exact pixel placement");
                    require(!source.isRecycled() && source.getPixel(0, 0) == pixels[0], "source immutable");
                } finally { if (result != source) result.recycle(); }
            }
        } finally { source.recycle(); }
        Bitmap partial = Bitmap.createBitmap(new int[]{0, 0x7f000000, 0xff123456, 0xffffffff},
                2, 2, Bitmap.Config.ARGB_8888);
        try {
            for (int rotation = 0; rotation < 4; rotation++) {
                Bitmap result = ProjectionGeometry.toLogical(partial, rotation);
                try {
                    require(!CapturePixelQuality.isFullyOpaque(result), "partial alpha still rejected");
                    int[] actual = new int[4]; result.getPixels(actual, 0, 2, 0, 0, 2, 2);
                    java.util.Arrays.sort(actual);
                    int[] want = {0, 0x7f000000, 0xff123456, 0xffffffff}; java.util.Arrays.sort(want);
                    require(java.util.Arrays.equals(actual, want), "all pixels and alpha retained");
                } finally { if (result != partial) result.recycle(); }
            }
        } finally { partial.recycle(); }
        return 28;
    }

    private static void require(boolean passed, String reason) { if (!passed) throw new AssertionError(reason); }
}
