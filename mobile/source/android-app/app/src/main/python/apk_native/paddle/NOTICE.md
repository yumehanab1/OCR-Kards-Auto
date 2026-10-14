# RapidOCR native port

Based on RapidOCR 1.4.4 (https://github.com/RapidAI/RapidOCR), retaining upstream
copyright/license headers. Paddle OCR code is Apache-2.0 licensed; modifications
replace ONNX inference with the Android Java bridge, replace Shapely quadrilateral
area/perimeter with OpenCV, and restrict loading to the supplied NumPy source image.
Model bytes are copied unchanged from the offline experiment; SHA256 manifest is
packaged under assets/native-ocr. No desktop ONNX Runtime binary is packaged.
