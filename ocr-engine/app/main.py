from fastapi import FastAPI, UploadFile, File, HTTPException
from pdf2image import convert_from_bytes
import pytesseract
from typing import List, Dict
import io

app = FastAPI(title="OCR Engine")

@app.post("/extract")
async def extract_text_from_pdf(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    try:
        contents = await file.read()
        
        # Convert PDF to images
        images = convert_from_bytes(contents)
        
        extracted_data = []
        
        for i, image in enumerate(images):
            # Extract text from image
            text = pytesseract.image_to_string(image)
            
            extracted_data.append({
                "page_number": i + 1,
                "text": text.strip()
            })
            
        return {"filename": file.filename, "pages": extracted_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
