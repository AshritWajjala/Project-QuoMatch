import pymupdf
import os
import ollama

pdf_path = "/home/lucifer/Projects/Project-QuoMatch/data/eCapsSOPH2024251502.pdf"
output_folder = "learn/images/"
os.makedirs(output_folder, exist_ok=True)

doc = pymupdf.open(pdf_path)

for page_num in range(len(doc)):
    page = doc[page_num]
    
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    
    output_filename = f"{output_folder}page_{page_num + 1}.png"
    
    pix.save(filename=output_filename)
    print(f"Saved: {output_filename}")
    
doc.close()