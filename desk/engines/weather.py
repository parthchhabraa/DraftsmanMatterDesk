from __future__ import annotations

import httpx

from .base import Engine

CODES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    80: "Showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


class WeatherEngine(Engine):
    name = "weather"

    def start(self):
        self.every(900, self.refresh)

    def refresh(self):
        loc = self.cfg.location
        if self.demo:
            self.hub.publish("weather", {
                "place": loc.name, "temp": 27, "feels": 28, "desc": "Partly cloudy", "kind": "cloud",
                "rain_pct": 10, "high": 31, "low": 19, "sunset": "17:41", "sunrise": "06:47",
                "hours": [{"h": f"{h:02d}", "t": t} for h, t in zip(range(6, 12), [26, 25, 24, 23, 22, 21])],
            })
            return
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": loc.latitude, "longitude": loc.longitude, "timezone": loc.timezone,
            "current": "temperature_2m,apparent_temperature,precipitation_probability,weather_code",
            "hourly": "temperature_2m", "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
            "forecast_days": 2,
        })
        r.raise_for_status()
        j = r.json()
        c, d = j["current"], j["daily"]
        code = c["weather_code"]
        now_idx = next((i for i, t in enumerate(j["hourly"]["time"]) if t >= c["time"]), 0)
        hours = [{"h": t[11:13], "t": round(v)} for t, v in
                 zip(j["hourly"]["time"][now_idx + 1:now_idx + 7], j["hourly"]["temperature_2m"][now_idx + 1:now_idx + 7])]
        kind = "rain" if code >= 51 else "fog" if code in (45, 48) else "cloud" if code >= 2 else "clear"
        self.hub.publish("weather", {
            "place": loc.name, "temp": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
            "desc": CODES.get(code, "Unsettled"), "kind": kind, "rain_pct": c.get("precipitation_probability") or 0,
            "high": round(d["temperature_2m_max"][0]), "low": round(d["temperature_2m_min"][0]),
            "sunrise": d["sunrise"][0][11:16], "sunset": d["sunset"][0][11:16], "hours": hours,
        })
