"""GitHub Actions'ta çalışır: saati gelen onaylı içerikleri Instagram'a paylaşır, LinkedIn için Telegram'a hatırlatma atar.
Gerekli gizli değerler (Settings > Secrets): IG_TOKEN, IG_USER_ID, TG_TOKEN, TG_CHAT"""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TR = timezone(timedelta(hours=3))
GRAPH = "https://graph.facebook.com"
DURUM = Path("durum.json")
GEC_KALMA = timedelta(hours=6)          # bundan daha geç kalan paylaşım yapılmaz, bildirilir


def istek(url, veri=None, yontem=None):
    data = urllib.parse.urlencode(veri).encode() if veri is not None else None
    req = urllib.request.Request(url, data=data, method=yontem or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        govde = e.read().decode(errors="replace")
        try:
            hata = json.loads(govde).get("error", {})
            raise RuntimeError(hata.get("error_user_msg") or hata.get("message") or govde[:300])
        except ValueError:
            raise RuntimeError(govde[:300])


def tg(metin, video=None):
    tok, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if not tok or not chat:
        return
    try:
        if video:
            istek(f"https://api.telegram.org/bot{tok}/sendVideo", {"chat_id": chat, "video": video, "caption": metin[:1000]})
        else:
            istek(f"https://api.telegram.org/bot{tok}/sendMessage", {"chat_id": chat, "text": metin[:4000], "disable_web_page_preview": "true"})
    except Exception as ex:
        print("telegram:", ex)


def ig_paylas(video_url, caption, tur):
    tok, ig = os.environ["IG_TOKEN"], os.environ["IG_USER_ID"]
    v = {"access_token": tok, "video_url": video_url}
    if tur == "story":
        v["media_type"] = "STORIES"
    else:
        v.update(media_type="REELS", share_to_feed="true", caption=caption)
    kap = istek(f"{GRAPH}/{ig}/media", v)["id"]
    for _ in range(40):                      # video işlenene kadar bekle (en fazla ~6-7 dk)
        time.sleep(10)
        d = istek(f"{GRAPH}/{kap}?" + urllib.parse.urlencode({"fields": "status_code,status", "access_token": tok}))
        if d.get("status_code") == "FINISHED":
            break
        if d.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram videoyu işleyemedi: {d.get('status', '')}")
    else:
        raise RuntimeError("Instagram video işleme zaman aşımı")
    return istek(f"{GRAPH}/{ig}/media_publish", {"creation_id": kap, "access_token": tok})["id"]


def main():
    durum = json.loads(DURUM.read_text(encoding="utf-8")) if DURUM.exists() else {}
    simdi = datetime.now(TR)
    ogeler = []
    for f in sorted(Path("takvim").glob("*.json")):
        ogeler += json.loads(f.read_text(encoding="utf-8"))
    for o in sorted(ogeler, key=lambda x: x["zaman"]):
        zaman = datetime.fromisoformat(o["zaman"])
        if zaman > simdi:
            continue
        for tur in ("post", "story", "linkedin"):
            anahtar = f"{o['id']}:{tur}"
            if anahtar in durum or not o.get(tur):
                continue
            if simdi - zaman > GEC_KALMA:
                durum[anahtar] = {"durum": "gecikti", "zaman": simdi.isoformat()}
                if tur == "post":
                    tg(f"⚠️ {o['ad']} ({zaman:%d.%m %H:%M}) zamanında paylaşılamadı ve 6 saatten fazla gecikti; atlandı.")
                continue
            try:
                if tur == "linkedin":
                    tg(f"💼 LinkedIn zamanı: {o['ad']}\nVideoyu kaydedip aşağıdaki yazıyla Netywork sayfasından paylaş.\n\n{o.get('caption_li', '')}", video=o[tur])
                    durum[anahtar] = {"durum": "hatirlatildi", "zaman": simdi.isoformat()}
                else:
                    mid = ig_paylas(o[tur], o.get("caption_ig", ""), tur)
                    durum[anahtar] = {"durum": "paylasildi", "id": mid, "zaman": simdi.isoformat()}
                    tg(f"✅ Instagram {'story' if tur == 'story' else 'gönderi'} paylaşıldı: {o['ad']}")
            except Exception as ex:
                hata_say = durum.get(anahtar + ":hata", 0) + 1
                durum[anahtar + ":hata"] = hata_say
                print(anahtar, ex)
                if hata_say in (1, 3):
                    tg(f"❌ {o['ad']} ({tur}) paylaşılamadı: {str(ex)[:300]}" + ("\nTekrar denenecek." if hata_say == 1 else ""))
                if hata_say >= 5:
                    durum[anahtar] = {"durum": "hata", "mesaj": str(ex)[:300], "zaman": simdi.isoformat()}
            DURUM.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
