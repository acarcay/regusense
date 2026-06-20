import pdfplumber

path = "/Users/acar/Desktop/tbmm_tutanak/28.dönem/1.yasamayılı/tbmm28001002.pdf"
try:
    with pdfplumber.open(path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")
        first_page = pdf.pages[0].extract_text()
        print("--- PAGE 1 ---")
        print(first_page[:500])
        print("--------------")
        
        # also print a random middle page
        mid_page = pdf.pages[len(pdf.pages)//2].extract_text()
        print(f"--- PAGE {len(pdf.pages)//2 + 1} ---")
        print(mid_page[:500])
        print("--------------")
except Exception as e:
    print(f"Error: {e}")
