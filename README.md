# PDF Heading Extractor

## 📌 Approach
- Uses PyMuPDF to extract text and style information.
- Detects headings using font size, bold, caps, density, and grammar patterns.
- Assigns hierarchical heading levels (H1-H6).
- Detects the document title as the largest text on the first page.

## 📦 Dependencies
- Python 3.10
- PyMuPDF

## 🛠️ Build & Run

### Build Docker Image:
docker build --platform linux/amd64 -t pdfextractor:latest .

### Run Docker Container:
docker run --rm -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output --network none pdfextractor:latest
