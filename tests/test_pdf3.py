import pdfplumber

path = "/Users/acar/Desktop/tbmm_tutanak/28.dönem/1.yasamayılı/tbmm28001004.pdf"
try:
    with pdfplumber.open(path) as pdf:
        for i in range(20, min(25, len(pdf.pages))):
            page_text = pdf.pages[i].extract_text()
            print(f"--- PAGE {i+1} ---")
            lines = page_text.split('\n')
            for line in lines[:30]:
                print(line)
except Exception as e:
    print(f"Error: {e}")
