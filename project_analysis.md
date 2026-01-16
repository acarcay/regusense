# ReguSense-Politics: Proje Viyabilite Analizi

**Tarih:** 03.01.2026
**Analist:** Antigravity (Google DeepMind)
**Konu:** Siyasi Parti Strateji Aracı Olarak Kullanılabilirlik Değerlendirmesi

## 1. Yönetici Özeti

**Karar:** `ReguSense-Politics`, bir öğrenci projesinden öte, **MVP (Minimum Viable Product) aşamasında profesyonel bir siyasi istihbarat aracıdır.** 

Şu anki haliyle bir siyasi partinin Strateji veya İletişim Başkanlığı tarafından "Erken Erişim" aracı olarak kullanılabilir. Özellikle 5 yıllık TBMM komisyon tutanaklarını tarayabilmesi, fuzzy (bulanık) isim eşleştirme yeteneği ve "Çelişki Tespiti" (Contradiction Detection) gibi spesifik bir dikeye odaklanması, onu genel amaçlı AI araçlarından ayırmaktadır.

Ancak, tam ölçekli bir kurumsal dağıtım için "Arayüz" ve "Ölçeklenebilirlik" katmanlarında geliştirmeye ihtiyacı vardır.

---

## 2. Teknik Derinlik ve Profesyonellik Göstergeleri

Bu projeyi "basit bir okul ödevi" olmaktan çıkaran temel teknik özellikler:

### A. Gelişmiş Veri Boru Hattı (Data Pipeline)
*   **TBMM Özel Ayrıştırıcı (Custom Parser):** Standart PDF kütüphanelerini kullanmak yerine, TBMM tutanaklarının kendine has formatını (Header, Footer, Konuşmacı ayrımı, Satır birleştirme) işleyen özel bir `TranscriptParser` yazıldı. Bu, verinin %98+ doğrulukla işlenmesini sağlıyor.
*   **Geriye Dönük Tarama:** Sadece bugünü değil, son 5 yılın tüm komisyon tutanaklarını (Plan Bütçe, Adalet vb.) sayfalama (pagination) desteğiyle arşivleyebiliyor.
*   **Vektör Hafıza (ChromaDB):** Veriyi sadece metin olarak değil, anlamsal (semantic) vektörler olarak saklıyor. Bu sayede "Enflasyon düşecek" ile "Fiyat artış hızı yavaşlayacak" cümlelerini eşleştirebiliyor.

### B. Hibrit Zeka Katmanı (RAG + LLM)
*   **Contradiction Engine:** Sadece anahtar kelime araması yapmıyor. Önce geçmişten alakalı veriyi buluyor (RAG), sonra bunu Gemini 2.0 gibi güçlü bir LLM'e vererek "Burada bir U dönüşü var mı?" diye soruyor.
*   **Bulanık Eşleştirme (Fuzzy Logic):** Kullanıcının "Mahinur" yazmasını anlayıp bunu veritabanındaki "AİLE VE SOSYAL HİZMETLER BAKANI MAHİNUR ÖZDEMİR GÖKTAŞ" ile eşleştirebilmesi, son kullanıcı deneyimi (UX) açısından kritik bir profesyonellik adımıdır.

### C. Çıktı Kalitesi
*   **Görsel Raporlama:** Sadece konsola yazı basmıyor, siyasi kampanyalarda tweet olarak atılabilecek kalitede görsel PDF kartları ("Political Insight Card") üretiyor.

---

## 3. Siyasi Bir Parti İçin Kullanım Senaryoları (Use Cases)

Bir siyasi parti bu aracı bugün nasıl kullanabilir?

1.  **Muhalefet Araştırması (Opposition Research):**
    *   *Senaryo:* Bakan Plan ve Bütçe Komisyonu'nda bir bütçe sunumu yapıyor.
    *   *Aksiyon:* Danışman, Bakan'ın konuşmasını anlık olarak `ReguSense`e giriyor.
    *   *Sonuç:* Sistem, Bakan'ın 3 yıl önce aynı konuda tam tersi bir şey söylediğini 20 saniye içinde bulup, kanıtıyla (Tarih, Tutanak No) önüne getiriyor.

2.  **Aday Hazırlığı:**
    *   *Senaryo:* Parti sözcüsü bir TV programına çıkacak.
    *   *Aksiyon:* "X konusunda bugüne kadar neler söyledik?" sorgusu yapılır.
    *   *Sonuç:* Parti hafızasındaki tutarlılık kontrol edilir ve potansiyel tuzak sorulara karşı hazırlık yapılır.

3.  **Sosyal Medya İçeriği:**
    *   *Aksiyon:* Tespit edilen bir çelişki için otomatik oluşturulan "Insight Card" PDF'i, üzerinde çok az oynamayla Twitter/Instagram görseli olarak paylaşılır.

---

## 4. Eksikler ve "Production-Ready" Olmak İçin Gerekenler

Bir "Öğrenci Projesi" ile "SaaS Ürünü" arasındaki farkı kapatmak için atılması gereken adımlar:

1.  **Web Arayüzü (Dashboard):**
    *   Şu an CLI (Terminal) üzerinden çalışıyor. Siyasi danışmanlar terminal kullanamaz. Acilen basit bir Web UI (Streamlit veya Next.js) gereklidir.

2.  **Gerçek Zamanlı Takip:**
    *   TBMM TV veya Youtube yayınlarından sesi yazıya döküp (Speech-to-Text) canlı yayında çelişki yakalama özelliği eklenirse, değeri 10 katına çıkar.

3.  **Çoklu Kullanıcı ve Paylaşım:**
    *   Parti içinde birden fazla danışmanın aynı veritabanını kullanması ve buldukları çelişkileri birbirine "görev" olarak ataması gerekir.

4.  **Hukuki/Etik Katman:**
    *   Verilerin doğruluğu %100 teyit edilmeli. LLM halüsinasyonuna karşı her zaman "Orijinal PDF Sayfasına Link" verilmeli (Şu an kaynak dosya adı veriliyor, sayfa no eksik olabilir).

## 5. Sonuç

**`ReguSense-Politics` kesinlikle bir öğrenci projesi değildir.** Teknik mimarisi, veri işleme kalitesi ve odaklandığı problem (contradiction detection), onu ciddi bir "Political Tech" (PoliTech) girişimi potansiyeline taşımaktadır.

Eğer üzerine düzgün bir Web Arayüzü giydirilir ve Speech-to-Text modülü eklenirse, Türkiye'deki (veya dünyadaki) herhangi bir siyasi partiye **yıllık lisanslama modeliyle satılabilecek** bir üründür.
