// Lightweight keyword-based tag extractor (MVP).
// Goal: turn freeform user text into a ranked list of tag IDs.
// This is deterministic, cheap, and easy to extend for new cities/tags.
//
// Later upgrade: replace internals with an LLM-backed extractor + validation.

function norm(s) {
  return (s || "")
    .toLowerCase()
    .replace(/[’']/g, "'")
    .replace(/[^a-z0-9\s\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const KEYWORDS = {
  cafes_brunch: ["cafe", "cafes", "coffee", "brunch", "breakfast", "bakery", "croissant"],
  restaurants: ["restaurant", "restaurants", "dining", "food scene", "food", "eat out"],
  nightlife: ["nightlife", "bar", "bars", "club", "clubs", "late", "party"],
  culture_museums: ["museum", "museums", "culture", "theatre", "theater", "concert", "opera"],
  art_design: ["art", "design", "gallery", "architecture", "creative"],
  shopping: ["shopping", "shops", "boutique", "boutiques", "retail"],
  local_market_vibe: ["market", "markets", "local vibe", "neighborhood vibe", "community"],
  touristy: ["tourist", "touristy", "tourists", "landmark", "sights", "sightseeing", "central sights"],
  families: ["family", "kids", "child", "children", "toddler", "baby", "playground", "stroller"],
  schools_strong: ["school", "schools", "kindergarten", "nursery", "preschool", "crèche", "creche", "daycare", "childcare"],
  expats_international: ["expat", "international", "english", "foreign", "multicultural", "embassy"],
  students: ["student", "students", "university", "campus"],
  young_professionals: ["young professional", "after work", "after-work", "startup", "cowork"],
  older_quiet: ["quiet", "calm", "peaceful", "sleepy", "residential", "older"],
  green_parks: ["park", "parks", "green", "nature", "trees", "garden", "gardens", "outdoors"],
  residential_quiet: ["quiet", "calm", "peaceful", "residential", "sleep", "noise"],
  urban_dense: ["urban", "dense", "city feel", "busy", "vibrant"],
  houses_more: ["house", "houses", "garden", "yard"],
  apartments_more: ["apartment", "apartments", "flat", "condo"],
  premium_feel: ["premium", "luxury", "upscale", "high-end", "exclusive"],
  value_for_money: ["value", "affordable", "price", "budget friendly", "good deal", "more space"],
  central_access: ["center", "centre", "downtown", "central", "close to center", "close to centre"],
  eu_quarter_access: ["eu quarter", "european quarter", "schuman", "luxembourg station", "place lux"],
  train_hubs_access: ["train", "station", "gare", "midi", "central station", "north station"],
  airport_access: ["airport", "zaventem"],
  metro_strong: ["metro", "subway", "underground"],
  tram_strong: ["tram"],
  bike_friendly: ["bike", "cycling", "bicycle"],
  car_friendly: ["car", "parking", "garage", "drive"],
  night_caution: ["unsafe", "safety", "at night", "night safety", "sketchy", "caution"],
  busy_traffic_noise: ["traffic", "noise", "noisy", "busy road"],
};

function scoreText(text) {
  const t = norm(text);
  const scores = {};
  for (const [tag, words] of Object.entries(KEYWORDS)) {
    let score = 0;
    for (const w of words) {
      const ww = norm(w);
      if (!ww) continue;
      // phrase match
      if (ww.includes(" ")) {
        if (t.includes(ww)) score += 3;
      } else {
        // word boundary-ish: split
        const parts = t.split(" ");
        if (parts.includes(ww)) score += 2;
        else if (t.includes(ww)) score += 1;
      }
    }
    if (score > 0) scores[tag] = score;
  }
  return scores;
}

export function extractTagsFromText(text, allTags) {
  const scores = scoreText(text);
  const tagIds = new Set((allTags || []).map(t => t.id));

  // keep only tags that exist in ALL_TAGS
  const entries = Object.entries(scores)
    .filter(([id]) => tagIds.has(id))
    .sort((a, b) => b[1] - a[1]);

  const ranked = entries.map(([id]) => id);

  // if nothing matched, return empty and let UI ask user to edit manually
  const top3 = ranked.slice(0, 3);
  const also = ranked.slice(3, 7);

  return {
    top3,
    also,
    ranked,
    scores,
  };
}
