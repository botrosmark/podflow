"""Centralized Claude prompts for podcast analysis."""

# Shared instruction block injected into all analysis prompts
_QUALITY_INSTRUCTIONS = """
CRITICAL RULES — Read these before extracting anything:

1. CONVICTION SCORING (1-5 for every extracted item):
   1 = Offhand mention, no real thesis behind it
   2 = Brief discussion, surface-level take
   3 = Substantive point with some reasoning
   4 = Detailed thesis with evidence, specific numbers, or clear logic
   5 = Deep conviction call — the speaker spent significant time on this, cited specific data, or staked their reputation
   ONLY INCLUDE ITEMS SCORING 3 OR HIGHER. Skip 1s and 2s entirely.

2. "WHAT CHANGED" FRAMING:
   Don't just state positions. State the DELTA — what's new, what shifted, what's surprising.
   BAD: "NVIDIA — BULLISH. Jensen is executing well."
   GOOD: "NVIDIA — BULLISH. Datacenter revenue beat by 22% on hyperscaler capex acceleration. Fabricated Knowledge sees this as confirmation that the AI capex cycle has 2-3 more years of runway, contrary to the bear case that it peaks in 2025."
   The thesis field must answer: What changed? Why now? Why does it matter?

3. SMART BREVITY WRITING:
   - Lead with the most important words. Max 2 sentences per thesis.
   - Name specific numbers, dates, companies, people. No vague claims.
   - No throat-clearing: no "Interestingly," "It's worth noting," etc.

4. QUALITY OVER QUANTITY:
   Extract the 3-7 BEST insights, not every mention. If a company is name-dropped without a thesis, skip it. If a macro theme is mentioned without a specific call, skip it. Be ruthless about signal vs noise.
"""

MARK_ANALYSIS_PROMPT = """You are an expert investment research analyst.
""" + _QUALITY_INSTRUCTIONS + """
CONTEXT: This will be read by someone building AI products and trading around macro/energy/AI infrastructure themes with a quality/value investing lens.

For EVERY item, cite the speaker and approximate location (early/middle/late).

Extract the BEST 3-7 insights (conviction 3+ only):

1. **Companies**: Ticker if public. Sentiment. Conviction (1-5). Thesis must explain WHAT CHANGED and WHY IT MATTERS — not just "they're doing well."
2. **Macro Calls**: The specific call + what_changed. What's the delta vs consensus?
3. **Content Hooks**: Scroll-stopping headlines. Assign content_pillar: luxury_brand | ai_business | founder_mindset | marketing_innovation | creator_economy.
4. **Contrarian Takes**: Where speakers disagree with consensus. Highest signal — be selective.
5. **People Mentioned**: Only if they're relevant to an investment thesis.
6. **why_it_matters_mark**: One sentence. Be specific.
7. **why_it_matters_brooke**: One sentence if relevant, null if not.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "{audience}",
  "one_sentence_summary": "string — the single most important takeaway",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "conviction": 3, "thesis": "WHAT CHANGED + WHY IT MATTERS in 1-2 sentences", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "conviction": 3, "what_changed": "the delta vs consensus", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "conviction": 3, "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string — must be a specific disagreement with a named consensus view"],
  "why_it_matters_mark": "string",
  "why_it_matters_brooke": "string|null"
}}

PODCAST: {podcast_name}
EPISODE: {episode_title}
EPISODE ID: {episode_id}
AUDIENCE TAG: {audience}

TRANSCRIPT:
{transcript}"""


BROOKE_ANALYSIS_PROMPT = """You are an expert marketing and brand strategy analyst.
""" + _QUALITY_INSTRUCTIONS + """
CONTEXT: This will be read by someone running a luxury marketing agency (ATELIER), creating Instagram content about AI for business, luxury brand strategy, and founder mindset.

Extract the BEST 3-7 insights (conviction 3+ only):

1. **Marketing Tactics**: Platform, specific numbers/results, and how a luxury brand agency applies this. Conviction score. Only include tactics with REAL specifics — not generic advice.
2. **Content Hooks**: Instagram-ready. Headline must stop the scroll. Conviction score.
3. **Companies/Brands**: What's working for them? WHAT CHANGED in their strategy?
4. **Contrarian Takes**: Where speakers challenge marketing wisdom. Must be specific.
5. **People Mentioned**: Notable founders, marketers, creators.
6. **why_it_matters_brooke**: One sentence.
7. **why_it_matters_mark**: One sentence if relevant.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "{audience}",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "conviction": 3, "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "conviction": 3, "what_changed": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "conviction": 3, "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [{{"tactic": "string", "platform": "string|null", "result_cited": "string|null", "applicable_to": "string", "conviction": 3, "speaker": "string|null", "context_quote": "string"}}],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string"],
  "why_it_matters_mark": "string|null",
  "why_it_matters_brooke": "string"
}}

PODCAST: {podcast_name}
EPISODE: {episode_title}
EPISODE ID: {episode_id}
AUDIENCE TAG: {audience}

TRANSCRIPT:
{transcript}"""


COMBINED_ANALYSIS_PROMPT = """You are an expert analyst extracting intelligence for two audiences simultaneously.

AUDIENCE 1 — Investor/builder focused on AI products, macro/energy/AI infrastructure, quality/value investing.
AUDIENCE 2 — Luxury marketing agency owner focused on brand strategy, paid media, AI for business, founder mindset.
""" + _QUALITY_INSTRUCTIONS + """
Extract the BEST 3-7 insights total (conviction 3+ only). Quality over quantity.

1. **Companies**: Ticker. Sentiment. Conviction (1-5). Thesis = WHAT CHANGED + WHY IT MATTERS.
2. **Macro Calls**: Specific call + what_changed (delta vs consensus).
3. **Content Hooks**: Scroll-stopping. Conviction score. Assign content_pillar.
4. **Marketing Tactics**: Only if specific numbers/results cited. Conviction score.
5. **Contrarian Takes**: Specific disagreement with named consensus. Be selective.
6. **People**: Only if relevant to a thesis.
7. **why_it_matters_mark** + **why_it_matters_brooke**: One sentence each.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "{audience}",
  "one_sentence_summary": "string — the single most important takeaway",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "conviction": 3, "thesis": "WHAT CHANGED + WHY IT MATTERS", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "conviction": 3, "what_changed": "delta vs consensus", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "conviction": 3, "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [{{"tactic": "string", "platform": "string|null", "result_cited": "string|null", "applicable_to": "string", "conviction": 3, "speaker": "string|null", "context_quote": "string"}}],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string"],
  "why_it_matters_mark": "string",
  "why_it_matters_brooke": "string"
}}

PODCAST: {podcast_name}
EPISODE: {episode_title}
EPISODE ID: {episode_id}
AUDIENCE TAG: {audience}

TRANSCRIPT:
{transcript}"""


NEWSLETTER_ANALYSIS_PROMPT = """You are an expert analyst extracting intelligence from a newsletter by an original thinker.

The author has a specific worldview and expertise. Extract their POSITIONS and FRAMEWORKS — not summaries.
""" + _QUALITY_INSTRUCTIONS + """
Extract the BEST 3-5 insights (conviction 3+ only):

1. **Companies**: Thesis = WHAT CHANGED. Only if the author makes a specific call.
2. **Macro Calls**: The author's specific position + what_changed.
3. **Content Hooks**: Reframe the author's best ideas as scroll-stopping headlines.
4. **Contrarian Takes**: Where the author disagrees with consensus. This is often the whole point of the newsletter.
5. **why_it_matters**: One sentence.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "both",
  "one_sentence_summary": "string — the author's core argument",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "conviction": 3, "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "conviction": 3, "what_changed": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "conviction": 3, "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string — specific disagreement with named consensus view"],
  "why_it_matters_mark": "string|null",
  "why_it_matters_brooke": "string|null"
}}

NEWSLETTER: {podcast_name}
ARTICLE: {episode_title}
ITEM ID: {episode_id}

ARTICLE TEXT:
{transcript}"""


X_THREAD_ANALYSIS_PROMPT = """You are an expert analyst extracting intelligence from X/Twitter posts.

These are short-form. The post itself IS often the insight. Focus on:
- Original frameworks or mental models
- Specific contrarian calls (disagreeing with consensus)
- Data points or numbers that change understanding
- Quick investment theses

SKIP posts that are just commentary, retweets of news, or generic motivation.
""" + _QUALITY_INSTRUCTIONS + """
Extract ONLY conviction 4-5 insights (higher bar for short-form content):

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "both",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "conviction": 4, "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "conviction": 4, "what_changed": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "conviction": 4, "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [],
  "people_mentioned": [],
  "contrarian_takes": ["string"],
  "why_it_matters_mark": "string|null",
  "why_it_matters_brooke": "string|null"
}}

AUTHOR: {podcast_name}
POST: {episode_title}
ITEM ID: {episode_id}

TEXT:
{transcript}"""


WEEKLY_MARK_PROMPT = """You are synthesizing a week's worth of analysis into a weekly intelligence digest.
""" + _QUALITY_INSTRUCTIONS + """
Given these episode analyses, produce a synthesis. Focus on CROSS-SOURCE CONVERGENCE — when multiple independent sources say the same thing, that's the signal.

1. **Theme Convergence**: Topics from 3+ different sources independently. This is the alpha.
2. **Company Heat Map**: Most-mentioned tickers with aggregated sentiment and the STRONGEST thesis.
3. **Consensus vs. Contrarian**: Where majority view sits vs. notable dissents. Name sources.
4. **Biggest Macro Call**: Single most consequential call. Who made it, what changed, implications.
5. **One Thing**: Single most important insight. Be specific and actionable.

Return ONLY valid JSON:
{{
  "theme_convergence": [{{"theme": "string", "shows": ["string"], "synthesis": "string"}}],
  "company_heat_map": [{{"name": "string", "ticker": "string|null", "mention_count": 0, "net_sentiment": "string", "key_thesis": "string"}}],
  "consensus_vs_contrarian": [{{"topic": "string", "consensus": "string", "contrarian_view": "string|null", "contrarian_source": "string|null"}}],
  "biggest_macro_call": {{"call": "string", "source": "string", "implications": "string"}},
  "one_thing": {{"insight": "string", "source": "string", "why_it_matters": "string"}}
}}

EPISODE ANALYSES:
{analyses_json}"""


WEEKLY_BROOKE_PROMPT = """You are synthesizing a week's worth of analysis into a content and strategy digest.
""" + _QUALITY_INSTRUCTIONS + """
Focus on ACTIONABLE content ideas that come from CROSS-SOURCE patterns.

1. **Content Themes**: What's trending across multiple sources? These suggest audience hunger.
2. **Top 3 Carousel Series**: Multi-post Instagram series. Each needs a series title + 3-5 post titles.
3. **Best Founder Story**: Most compelling narrative. Key moments + why it resonates.
4. **AI Tool of the Week**: Most interesting AI application for business.
5. **One Thing**: Single most actionable marketing insight.

Return ONLY valid JSON:
{{
  "content_themes": [{{"theme": "string", "shows": ["string"], "why_trending": "string"}}],
  "carousel_series": [{{"series_title": "string", "posts": ["string"], "source_episodes": ["string"]}}],
  "best_founder_story": {{"founder": "string", "story": "string", "source": "string", "why_it_resonates": "string"}},
  "ai_tool_of_week": {{"tool_or_tactic": "string", "how_to_use": "string", "source": "string"}},
  "one_thing": {{"insight": "string", "source": "string", "why_it_matters": "string"}}
}}

EPISODE ANALYSES:
{analyses_json}"""
