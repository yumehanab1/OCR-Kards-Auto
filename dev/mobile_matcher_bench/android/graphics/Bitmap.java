package android.graphics;

public final class Bitmap {
    public enum Config { ARGB_8888 }
    private final int width, height;
    private final int[] pixels;
    public Bitmap(int width, int height, int[] pixels) {
        this.width = width; this.height = height; this.pixels = pixels;
    }
    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public boolean isRecycled() { return false; }
    public void getPixels(int[] out, int offset, int stride, int x, int y, int w, int h) {
        for (int row = 0; row < h; row++)
            System.arraycopy(pixels, (y + row) * width + x, out, offset + row * stride, w);
    }
}
