"""
Neo4j Graf Yardımcı Sınıfı (GraphHelper).

Temel CRUD operasyonlarını kapsayan senkron/asenkron Neo4j wrapper'ı:

Düğüm oluşturma:
    - Siyasetçi   (Politician)
    - Kurum        (Organization / public_institution tipi)
    - Şirket       (Organization / company tipi)

İlişki oluşturma (Türkçe etiketler):
    - UYESIDIR     : Siyasetçi → Kurum/Şirket üyeliği
    - KAZANDI      : Siyasetçi/Şirket → İhale/RegulatoryAction kazanımı
    - SAHIBIDIR    : Siyasetçi → Şirket sahipliği

Kullanım::

    from database.graph_helper import GraphHelper

    helper = GraphHelper()

    # Düğüm oluştur
    await helper.create_siyasetci(pg_id=1, ad="Ahmet Yılmaz", parti="CHP")
    await helper.create_kurum(ad="EPDK", kurum_tipi="düzenleyici kurum")
    await helper.create_sirket(ad="ABC İnşaat A.Ş.", mersis_no="0123456789")

    # İlişki kur
    await helper.uyesidir(siyasetci_id=1, org_adi="EPDK", rol="Üye")
    await helper.kazandi(sirket_mersis="0123456789", ihale_id="2024-IHK-001")
    await helper.sahibidir(siyasetci_id=1, sirket_mersis="0123456789", pay_orani=0.51)
"""

import logging
from datetime import date
from typing import Optional, Any

from database.neo4j_client import run_query, run_write, get_connection_weight

logger = logging.getLogger(__name__)


class GraphHelper:
    """
    Neo4j CRUD işlemlerini tek noktadan yöneten yardımcı sınıf.

    Tüm metodlar async'tir ve ``database.neo4j_client.run_write`` /
    ``run_query`` fonksiyonlarını kullanır.

    Düğüm etiketleri:
        - ``Politician``    – Siyasetçi
        - ``Organization``  – Kurum veya Şirket (``type`` alanıyla ayrışır)

    İlişki etiketleri (Türkçe):
        - ``UYESIDIR``      – Kurum/komite üyeliği
        - ``KAZANDI``       – İhale veya lisans kazanımı
        - ``SAHIBIDIR``     – Hisse / mülkiyet sahipliği
    """

    # =========================================================================
    # Düğüm Oluşturma
    # =========================================================================

    async def create_siyasetci(
        self,
        pg_id: int,
        ad: str,
        normalized_ad: str = "",
        parti: str = "",
        unvan: str = "",
        muhalefet_mi: bool = False,
    ) -> dict[str, Any]:
        """
        Siyasetçi düğümü oluşturur veya mevcutu günceller (MERGE).

        Args:
            pg_id:          PostgreSQL ``speakers.id`` değeri (benzersiz anahtar)
            ad:             Tam adı (örn. "Kemal Kılıçdaroğlu")
            normalized_ad:  ASCII normalleştirilmiş adı (örn. "kemal kilicdaroglu")
            parti:          Parti kısaltması (örn. "CHP", "AKP")
            unvan:          Unvan (örn. "Milletvekili", "Bakan")
            muhalefet_mi:   Muhalefet partisine üyeyse True

        Returns:
            Yazma işlemi özeti (nodes_created, properties_set, …)
        """
        cypher = """
        MERGE (p:Politician {pg_id: $pg_id})
        SET p.name             = $ad,
            p.normalized_name  = $normalized_ad,
            p.party            = $parti,
            p.title            = $unvan,
            p.is_opposition    = $muhalefet_mi,
            p.updated_at       = datetime()
        RETURN p
        """
        result = await run_write(cypher, {
            "pg_id":         pg_id,
            "ad":            ad,
            "normalized_ad": normalized_ad or ad.lower(),
            "parti":         parti,
            "unvan":         unvan,
            "muhalefet_mi":  muhalefet_mi,
        })
        logger.info("Siyasetçi düğümü oluşturuldu/güncellendi: %s (pg_id=%d)", ad, pg_id)
        return result

    async def create_kurum(
        self,
        ad: str,
        kurum_tipi: str = "public_institution",
        kisa_ad: Optional[str] = None,
        aciklama: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Kamu kurumu düğümü oluşturur veya mevcutu günceller.

        ``type`` alanı ``public_institution`` olarak set edilir; bu sayede
        şirketlerden ayırt edilebilir.

        Args:
            ad:          Kurumun tam adı (örn. "Enerji Piyasası Düzenleme Kurumu")
            kurum_tipi:  Neo4j ``type`` özelliği (varsayılan: "public_institution")
            kisa_ad:     Kısaltma (örn. "EPDK")
            aciklama:    Açıklayıcı metin

        Returns:
            Yazma işlemi özeti
        """
        cypher = """
        MERGE (o:Organization {name: $ad})
        SET o.type        = $kurum_tipi,
            o.short_name  = $kisa_ad,
            o.description = $aciklama,
            o.updated_at  = datetime()
        RETURN o
        """
        result = await run_write(cypher, {
            "ad":         ad,
            "kurum_tipi": kurum_tipi,
            "kisa_ad":    kisa_ad,
            "aciklama":   aciklama,
        })
        logger.info("Kurum düğümü oluşturuldu/güncellendi: %s", ad)
        return result

    async def create_sirket(
        self,
        ad: str,
        mersis_no: Optional[str] = None,
        vergi_no: Optional[str] = None,
        sirket_tipi: str = "company",
        sektor: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Şirket düğümü oluşturur veya mevcutu günceller.

        Birincil anahtar olarak MERSİS numarası kullanılır; yoksa isim kullanılır.

        Args:
            ad:          Şirket adı (örn. "ABC İnşaat A.Ş.")
            mersis_no:   MERSİS sicil numarası (opsiyonel ama önerilir)
            vergi_no:    Vergi kimlik numarası
            sirket_tipi: "company" | "holding" | "foundation" | "association"
            sektor:      Sektör kodu (örn. "CONSTRUCTION", "ENERGY")

        Returns:
            Yazma işlemi özeti
        """
        if mersis_no:
            cypher = """
            MERGE (o:Organization {mersis_no: $mersis_no})
            SET o.name       = $ad,
                o.vergi_no   = $vergi_no,
                o.type       = $sirket_tipi,
                o.sector     = $sektor,
                o.updated_at = datetime()
            RETURN o
            """
        else:
            cypher = """
            MERGE (o:Organization {name: $ad})
            SET o.type       = $sirket_tipi,
                o.vergi_no   = $vergi_no,
                o.sector     = $sektor,
                o.updated_at = datetime()
            RETURN o
            """
        result = await run_write(cypher, {
            "ad":          ad,
            "mersis_no":   mersis_no,
            "vergi_no":    vergi_no,
            "sirket_tipi": sirket_tipi,
            "sektor":      sektor,
        })
        logger.info("Şirket düğümü oluşturuldu/güncellendi: %s (MERSIS=%s)", ad, mersis_no)
        return result

    # =========================================================================
    # İlişki Oluşturma
    # =========================================================================

    async def uyesidir(
        self,
        siyasetci_pg_id: int,
        org_adi: str,
        rol: str = "",
        baslangic_tarihi: Optional[str] = None,
        bitis_tarihi: Optional[str] = None,
        kaynak: str = "",
    ) -> dict[str, Any]:
        """
        ``(Politician)-[:UYESIDIR]->(Organization)`` ilişkisi oluşturur.

        Bu ilişki; milletvekili komisyon üyeliği, yönetim kurulu üyeliği
        veya dernek/vakıf üyeliğini temsil eder.

        Args:
            siyasetci_pg_id:  Siyasetçinin PostgreSQL ID'si
            org_adi:          Kurum/şirket adı (Neo4j'de ``name`` özelliği)
            rol:              Üyelik rolü (örn. "Komisyon Başkanı", "Üye")
            baslangic_tarihi: Üyelik başlangıcı (YYYY-MM-DD)
            bitis_tarihi:     Üyelik sonu – None ise hâlâ aktif
            kaynak:           Kaynağa referans (URL veya belge adı)

        Returns:
            Yazma işlemi özeti
        """
        cypher = """
        MATCH (p:Politician {pg_id: $siyasetci_pg_id})
        MATCH (o:Organization {name: $org_adi})
        MERGE (p)-[r:UYESIDIR]->(o)
        SET r.rol              = $rol,
            r.baslangic_tarihi = $baslangic_tarihi,
            r.bitis_tarihi     = $bitis_tarihi,
            r.kaynak           = $kaynak,
            r.aktif            = ($bitis_tarihi IS NULL),
            r.guncellendi      = datetime()
        RETURN r
        """
        result = await run_write(cypher, {
            "siyasetci_pg_id": siyasetci_pg_id,
            "org_adi":         org_adi,
            "rol":             rol,
            "baslangic_tarihi": baslangic_tarihi,
            "bitis_tarihi":    bitis_tarihi,
            "kaynak":          kaynak,
        })
        logger.info(
            "UYESIDIR ilişkisi: pg_id=%d → %s (rol=%s)",
            siyasetci_pg_id, org_adi, rol,
        )
        return result

    async def kazandi(
        self,
        sirket_mersis: Optional[str] = None,
        sirket_adi: Optional[str] = None,
        ihale_id: Optional[str] = None,
        ihale_tutari: Optional[float] = None,
        para_birimi: str = "TRY",
        tarih: Optional[str] = None,
        kaynak: str = "",
    ) -> dict[str, Any]:
        """
        ``(Organization)-[:KAZANDI]->(RegulatoryAction)`` ilişkisi oluşturur.

        İhale veya lisans kararını kimin kazandığını gösterir. Eğer
        ``RegulatoryAction`` düğümü yoksa otomatik olarak oluşturulur
        (MERGE kullanılır).

        Args:
            sirket_mersis:  Şirketin MERSİS numarası (birini verin: mersis veya ad)
            sirket_adi:     Şirket adı (MERSİS yoksa kullanılır)
            ihale_id:       İhale kimliği (IKN, belge numarası vb.)
            ihale_tutari:   İhale/sözleşme tutarı
            para_birimi:    Para birimi kodu (varsayılan: "TRY")
            tarih:          Karar/kazanım tarihi (YYYY-MM-DD)
            kaynak:         Kaynak URL veya belge adı

        Returns:
            Yazma işlemi özeti

        Raises:
            ValueError: Ne ``sirket_mersis`` ne de ``sirket_adi`` verilmemişse
        """
        if not sirket_mersis and not sirket_adi:
            raise ValueError("sirket_mersis veya sirket_adi parametrelerinden biri zorunludur.")

        # Şirketi MERSİS veya ada göre eşleştir
        if sirket_mersis:
            match_org = "MATCH (o:Organization {mersis_no: $sirket_mersis})"
            params: dict[str, Any] = {"sirket_mersis": sirket_mersis}
        else:
            match_org = "MATCH (o:Organization {name: $sirket_adi})"
            params = {"sirket_adi": sirket_adi}

        cypher = f"""
        {match_org}
        MERGE (a:RegulatoryAction {{action_id: $ihale_id}})
        ON CREATE SET
            a.action_type = 'tender',
            a.date        = $tarih,
            a.source_url  = $kaynak,
            a.created_at  = datetime()
        MERGE (o)-[r:KAZANDI]->(a)
        SET r.tutar       = $ihale_tutari,
            r.para_birimi = $para_birimi,
            r.tarih       = $tarih,
            r.kaynak      = $kaynak,
            r.guncellendi = datetime()
        RETURN r
        """
        params.update({
            "ihale_id":    ihale_id or "BILINMIYOR",
            "ihale_tutari": ihale_tutari,
            "para_birimi": para_birimi,
            "tarih":       tarih,
            "kaynak":      kaynak,
        })
        result = await run_write(cypher, params)
        logger.info(
            "KAZANDI ilişkisi: %s → ihale=%s (tutar=%.2f %s)",
            sirket_mersis or sirket_adi,
            ihale_id,
            ihale_tutari or 0.0,
            para_birimi,
        )
        return result

    async def sahibidir(
        self,
        siyasetci_pg_id: int,
        sirket_mersis: Optional[str] = None,
        sirket_adi: Optional[str] = None,
        pay_orani: Optional[float] = None,
        direkt_mi: bool = True,
        baslangic_tarihi: Optional[str] = None,
        bitis_tarihi: Optional[str] = None,
        kaynak: str = "",
    ) -> dict[str, Any]:
        """
        ``(Politician)-[:SAHIBIDIR]->(Organization)`` ilişkisi oluşturur.

        Hisse senedi, mülkiyet veya fiilî kontrol sahipliğini temsil eder.
        Çakışma skoru (``conflict_score``) otomatik olarak hesaplanır.

        Args:
            siyasetci_pg_id: Siyasetçinin PostgreSQL ID'si
            sirket_mersis:   Şirketin MERSİS numarası
            sirket_adi:      Şirket adı (MERSİS yoksa)
            pay_orani:       Hisse oranı 0.0–1.0 arasında (örn. 0.51 = %51)
            direkt_mi:       True = doğrudan sahiplik; False = dolaylı (vekâleten)
            baslangic_tarihi: Sahipliğin başladığı tarih (YYYY-MM-DD)
            bitis_tarihi:    Sahipliğin bittiği tarih – None ise hâlâ aktif
            kaynak:          Kaynak belgesi

        Returns:
            Yazma işlemi özeti

        Raises:
            ValueError: Ne ``sirket_mersis`` ne de ``sirket_adi`` verilmemişse
        """
        if not sirket_mersis and not sirket_adi:
            raise ValueError("sirket_mersis veya sirket_adi parametrelerinden biri zorunludur.")

        # Çakışma skoru: sahiplik tipi "shareholder" olarak değerlendirilir
        connection_type = "shareholder"
        end_date_obj: Optional[date] = None
        if bitis_tarihi:
            try:
                end_date_obj = date.fromisoformat(bitis_tarihi)
            except ValueError:
                pass

        from database.neo4j_client import calculate_conflict_score
        conflict_score = calculate_conflict_score(connection_type, end_date_obj)

        if sirket_mersis:
            match_org = "MATCH (o:Organization {mersis_no: $sirket_mersis})"
            params: dict[str, Any] = {"sirket_mersis": sirket_mersis}
        else:
            match_org = "MATCH (o:Organization {name: $sirket_adi})"
            params = {"sirket_adi": sirket_adi}

        cypher = f"""
        MATCH (p:Politician {{pg_id: $siyasetci_pg_id}})
        {match_org}
        MERGE (p)-[r:SAHIBIDIR]->(o)
        SET r.pay_orani       = $pay_orani,
            r.direkt          = $direkt_mi,
            r.baslangic_tarihi = $baslangic_tarihi,
            r.bitis_tarihi    = $bitis_tarihi,
            r.aktif           = ($bitis_tarihi IS NULL),
            r.conflict_score  = $conflict_score,
            r.kaynak          = $kaynak,
            r.guncellendi     = datetime()
        RETURN r
        """
        params.update({
            "siyasetci_pg_id":  siyasetci_pg_id,
            "pay_orani":        pay_orani,
            "direkt_mi":        direkt_mi,
            "baslangic_tarihi": baslangic_tarihi,
            "bitis_tarihi":     bitis_tarihi,
            "conflict_score":   conflict_score,
            "kaynak":           kaynak,
        })
        result = await run_write(cypher, params)
        logger.info(
            "SAHIBIDIR ilişkisi: pg_id=%d → %s (pay=%.1f%%, skor=%.2f)",
            siyasetci_pg_id,
            sirket_mersis or sirket_adi,
            (pay_orani or 0) * 100,
            conflict_score,
        )
        return result

    # =========================================================================
    # Sorgulama Yardımcıları
    # =========================================================================

    async def siyasetci_getir(self, pg_id: int) -> dict[str, Any]:
        """Siyasetçiyi pg_id ile getirir."""
        cypher = "MATCH (p:Politician {pg_id: $pg_id}) RETURN p"
        results = await run_query(cypher, {"pg_id": pg_id})
        return results[0] if results else {}

    async def org_getir(self, ad: str) -> dict[str, Any]:
        """Kurum/Şirketi adıyla getirir."""
        cypher = "MATCH (o:Organization {name: $ad}) RETURN o"
        results = await run_query(cypher, {"ad": ad})
        return results[0] if results else {}

    async def sahiplikler_listele(
        self,
        siyasetci_pg_id: int,
        sadece_aktif: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Siyasetçinin tüm sahiplik ilişkilerini listeler.

        Args:
            siyasetci_pg_id: Siyasetçinin PostgreSQL ID'si
            sadece_aktif:    True ise sadece aktif sahiplikleri döner

        Returns:
            Sahiplik kayıtlarının listesi
        """
        aktif_filtre = "AND r.aktif = true" if sadece_aktif else ""
        cypher = f"""
        MATCH (p:Politician {{pg_id: $pg_id}})-[r:SAHIBIDIR]->(o:Organization)
        WHERE 1=1 {aktif_filtre}
        RETURN p.name      AS siyasetci,
               o.name      AS sirket,
               o.mersis_no AS mersis,
               r.pay_orani AS pay_orani,
               r.aktif     AS aktif,
               r.conflict_score AS conflict_score
        ORDER BY r.conflict_score DESC
        """
        return await run_query(cypher, {"pg_id": siyasetci_pg_id})

    async def uyelikler_listele(
        self,
        siyasetci_pg_id: int,
        sadece_aktif: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Siyasetçinin tüm kurum üyeliklerini listeler.

        Args:
            siyasetci_pg_id: Siyasetçinin PostgreSQL ID'si
            sadece_aktif:    True ise sadece devam eden üyelikleri döner

        Returns:
            Üyelik kayıtlarının listesi
        """
        aktif_filtre = "AND r.aktif = true" if sadece_aktif else ""
        cypher = f"""
        MATCH (p:Politician {{pg_id: $pg_id}})-[r:UYESIDIR]->(o:Organization)
        WHERE 1=1 {aktif_filtre}
        RETURN p.name AS siyasetci,
               o.name AS kurum,
               o.type AS kurum_tipi,
               r.rol  AS rol,
               r.aktif AS aktif,
               r.baslangic_tarihi AS baslangic
        ORDER BY r.baslangic_tarihi DESC
        """
        return await run_query(cypher, {"pg_id": siyasetci_pg_id})

    async def ihale_kazanimlari_listele(
        self,
        sirket_mersis: Optional[str] = None,
        sirket_adi: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Şirketin kazandığı ihaleleri listeler.

        Args:
            sirket_mersis: MERSİS numarasıyla arama
            sirket_adi:    Şirket adıyla arama (MERSİS yoksa)

        Returns:
            Kazanılan ihalelerin listesi
        """
        if sirket_mersis:
            match_org = "MATCH (o:Organization {mersis_no: $sirket_mersis})"
            params: dict[str, Any] = {"sirket_mersis": sirket_mersis}
        elif sirket_adi:
            match_org = "MATCH (o:Organization {name: $sirket_adi})"
            params = {"sirket_adi": sirket_adi}
        else:
            raise ValueError("sirket_mersis veya sirket_adi verilmelidir.")

        cypher = f"""
        {match_org}
        MATCH (o)-[r:KAZANDI]->(a:RegulatoryAction)
        RETURN o.name      AS sirket,
               a.action_id AS ihale_id,
               a.date      AS tarih,
               r.tutar     AS tutar,
               r.para_birimi AS para_birimi
        ORDER BY a.date DESC
        """
        return await run_query(cypher, params)

    async def istatistikler(self) -> dict[str, int]:
        """Graf istatistiklerini döner."""
        cypher = """
        MATCH (p:Politician)         WITH count(p) AS siyasetci_sayisi
        MATCH (o:Organization)       WITH siyasetci_sayisi, count(o) AS org_sayisi
        MATCH ()-[u:UYESIDIR]->()    WITH siyasetci_sayisi, org_sayisi, count(u) AS uye_sayisi
        MATCH ()-[k:KAZANDI]->()     WITH siyasetci_sayisi, org_sayisi, uye_sayisi, count(k) AS kazanim_sayisi
        MATCH ()-[s:SAHIBIDIR]->()   RETURN siyasetci_sayisi, org_sayisi, uye_sayisi, kazanim_sayisi, count(s) AS sahiplik_sayisi
        """
        results = await run_query(cypher)
        return results[0] if results else {
            "siyasetci_sayisi": 0,
            "org_sayisi": 0,
            "uye_sayisi": 0,
            "kazanim_sayisi": 0,
            "sahiplik_sayisi": 0,
        }
