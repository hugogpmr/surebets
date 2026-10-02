from providers.browser import _HEAVY_URL


def test_only_images_media_and_fonts_are_blocked():
    blocked = [
        "https://www.zebet.es/img/logo.png",
        "https://cdn.x.com/a/b/photo.JPG?w=300",
        "https://x.com/fonts/roboto.woff2#v2",
        "https://x.com/promo.mp4",
        "https://x.com/icons/flag.svg",
    ]
    allowed = [
        "https://spectate-web.888sport.es/spectate/sportsbook/getEventData/football/x/y/z/123",
        "https://www.zebet.es/es/competition/306-laliga",
        "https://x.com/app.js",
        "https://x.com/styles.css",
        "https://x.com/api/png-export",  # "png" en la ruta, no como extensión
    ]
    assert all(_HEAVY_URL.search(url) for url in blocked)
    assert not any(_HEAVY_URL.search(url) for url in allowed)
