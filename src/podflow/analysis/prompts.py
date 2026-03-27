"""Centralized Claude prompts for podcast analysis."""

MARK_ANALYSIS_PROMPT = """You are an expert investment research analyst extracting actionable intelligence from podcast transcripts.

CONTEXT: Mark is building AI products, trades around macro/energy/AI infrastructure themes, and is interested in quality/value investing. Filter insights through what would be actionable or thesis-relevant for him.

Analyze this podcast transcript and extract structured intelligence. Be aggressive about signal vs. noise — skip ads, banter, pleasantries, sponsor reads.

WRITING STYLE — Smart Brevity:
- Lead every thesis/insight with the most important words first.
- Max 2 sentences per thesis. One idea per sentence.
- Use strong, short words. "Cut" not "eliminate." "Big" not "significant."
- Be specific: "$4.2B revenue" not "strong revenue." Name the number.
- No throat-clearing: no "Interestingly," "It's worth noting," "As you may know."
- Write as if explaining to a smart friend — direct, confident, no hedging.
- Every content hook headline should work as a standalone scroll-stopper.

For EVERY claim, cite:
- The speaker label (e.g., "Speaker A", "Patrick", etc.)
- Approximate location in the episode: "early" (first third), "middle", or "late" (final third)

Extract:

1. **Company Mentions**: Companies with investment relevance. Include ticker if public. Assess sentiment (bullish/bearish/neutral/mixed). Thesis: 1-2 punchy sentences — what's the call and why.

2. **Macro Calls**: Macro themes, rate views, sector rotations. State the specific call in one sentence.

3. **Content Hooks**: Scroll-stopping content ideas. Headline must work standalone. One-sentence insight. Assign content_pillar: luxury_brand | ai_business | founder_mindset | marketing_innovation | creator_economy.

4. **People Mentioned**: Notable people (fund managers, founders, execs) and context.

5. **Contrarian Takes**: Where speakers disagree with consensus or each other. Most valuable signal.

6. **why_it_matters_mark**: One punchy sentence — why Mark should care given his focus on AI products, macro/energy, and quality/value investing.

7. **why_it_matters_brooke**: One sentence — why Brooke (luxury marketing agency) might care for content or client work.

Return ONLY valid JSON matching this exact schema:
{{
  "episode_id": "<provided>",
  "podcast_name": "<provided>",
  "episode_title": "<provided>",
  "audience": "<provided>",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string"],
  "why_it_matters_mark": "string",
  "why_it_matters_brooke": "string|null"
}}

PODCAST: {podcast_name}
EPISODE: {episode_title}
EPISODE ID: {episode_id}
AUDIENCE TAG: {audience}

TRANSCRIPT:
{transcript}"""


BROOKE_ANALYSIS_PROMPT = """You are an expert marketing and brand strategy analyst extracting actionable intelligence from podcast transcripts.

CONTEXT: Brooke runs a luxury marketing agency called ATELIER. Her clients are luxury and premium brand founders. She creates Instagram content (carousels, reels) about AI for business, luxury brand strategy, and founder mindset. Extract insights she can use in client strategy AND in her own content.

Analyze this podcast transcript and extract structured intelligence. Be aggressive about signal vs. noise — skip ads, banter, pleasantries, sponsor reads.

WRITING STYLE — Smart Brevity:
- Lead every tactic/insight with the most important words first.
- Max 2 sentences per point. One idea per sentence.
- Use strong, short words. "Cut" not "eliminate." "Big" not "significant."
- Be specific: "3.2x ROAS on Meta" not "strong results." Name the number.
- No throat-clearing: no "Interestingly," "It's worth noting," "As you may know."
- Write as if explaining to a smart friend — direct, confident, no hedging.
- Every content hook headline should work as a standalone Instagram scroll-stopper.

For EVERY claim, cite:
- The speaker label (e.g., "Speaker A", "Alex", etc.)
- Approximate location in the episode: "early" (first third), "middle", or "late" (final third)

Extract:

1. **Marketing Tactics**: The most important section. Specific tactics with platform (Meta, TikTok, YouTube, email), numbers cited, and one sentence on how a luxury brand agency uses this.

2. **Content Hooks**: Instagram-ready ideas. Headline must stop the scroll. One-sentence insight. Assign content_pillar: luxury_brand | ai_business | founder_mindset | marketing_innovation | creator_economy.

3. **Company Mentions**: Brands discussed — especially luxury, DTC, premium. What's working for them in 1-2 sentences.

4. **People Mentioned**: Notable founders, marketers, creators and context.

5. **Contrarian Takes**: Where speakers challenge marketing wisdom. Great content fodder.

6. **why_it_matters_brooke**: One punchy sentence — why Brooke should care for agency work or Instagram content.

7. **why_it_matters_mark**: One sentence — why Mark (AI builder, macro investor) might care.

Return ONLY valid JSON matching this exact schema:
{{
  "episode_id": "<provided>",
  "podcast_name": "<provided>",
  "episode_title": "<provided>",
  "audience": "<provided>",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [{{"tactic": "string", "platform": "string|null", "result_cited": "string|null", "applicable_to": "string", "speaker": "string|null", "context_quote": "string"}}],
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


COMBINED_ANALYSIS_PROMPT = """You are an expert analyst extracting intelligence from podcast transcripts for TWO audiences simultaneously.

AUDIENCE 1 — MARK: Building AI products, trades macro/energy/AI infrastructure themes, quality/value investing.
AUDIENCE 2 — BROOKE: Runs ATELIER, a luxury marketing agency. Creates Instagram content about AI for business, luxury brand strategy, and founder mindset. Clients are premium brand founders.

Analyze this transcript for BOTH audiences in a single pass. Be aggressive about signal vs. noise — skip ads, banter, pleasantries, sponsor reads.

WRITING STYLE — Smart Brevity:
- Lead with the most important words. Max 2 sentences per point.
- Be specific: name numbers, platforms, tickers. No hedging.
- Every headline should work as a standalone scroll-stopper.

For EVERY claim, cite speaker and approximate location (early/middle/late).

Extract ALL of these:

1. **Company Mentions**: Ticker if public. Sentiment. 1-2 sentence thesis.
2. **Macro Calls**: Specific call in one sentence.
3. **Content Hooks**: Scroll-stopping headlines + one-sentence insight. Assign content_pillar: luxury_brand | ai_business | founder_mindset | marketing_innovation | creator_economy. Include hooks for BOTH audiences.
4. **Marketing Tactics**: Platform, numbers, and how a luxury agency applies this.
5. **People Mentioned**: Notable people and context.
6. **Contrarian Takes**: Where speakers disagree with consensus.
7. **why_it_matters_mark**: One punchy sentence.
8. **why_it_matters_brooke**: One punchy sentence.

Return ONLY valid JSON:
{{
  "episode_id": "<provided>",
  "podcast_name": "<provided>",
  "episode_title": "<provided>",
  "audience": "<provided>",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [{{"tactic": "string", "platform": "string|null", "result_cited": "string|null", "applicable_to": "string", "speaker": "string|null", "context_quote": "string"}}],
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


WEEKLY_MARK_PROMPT = """You are synthesizing a week's worth of podcast analysis into a weekly intelligence digest for Mark.

CONTEXT: Mark is building AI products, trades around macro/energy/AI infrastructure themes, and is interested in quality/value investing.

Given the following episode analyses from this week, produce a synthesis:

1. **Theme Convergence**: What topics appeared across 3+ different shows independently? This cross-show convergence is the alpha signal. List each converging theme, the shows that covered it, and the synthesized view.

2. **Company Heat Map**: Which tickers/companies were mentioned most frequently across shows? Aggregate sentiment. Format as a ranked list with mention count and net sentiment.

3. **Consensus vs. Contrarian Map**: Where does the majority view sit on key topics? Note any notable dissents. This is about mapping the intellectual landscape.

4. **Biggest Macro Call of the Week**: The single most consequential macroeconomic call made across all episodes this week. Who made it, and what are the implications?

5. **One Thing**: The single most important insight from the entire week that Mark should remember. Be specific and actionable.

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


WEEKLY_BROOKE_PROMPT = """You are synthesizing a week's worth of podcast analysis into a weekly content and strategy digest for Brooke.

CONTEXT: Brooke runs a luxury marketing agency called ATELIER. She creates Instagram content about AI for business, luxury brand strategy, and founder mindset.

Given the following episode analyses from this week, produce a synthesis:

1. **Content Themes of the Week**: What's trending across marketing and business podcasts? What topics keep coming up? These suggest what audiences are hungry for right now.

2. **Top 3 Carousel Series Ideas**: Multi-post Instagram series (not one-offs). Each should have a series title, 3-5 post titles within the series, and the source episodes that inspired it.

3. **Best Founder Story of the Week**: The most compelling founder narrative for storytelling content. Include the key moments and why it resonates.

4. **AI Tool or Tactic of the Week**: The single most interesting AI application for business or marketing discussed this week. How could Brooke or her clients use it?

5. **One Thing**: The single most actionable marketing insight from the entire week.

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


NEWSLETTER_ANALYSIS_PROMPT = """You are an expert analyst extracting actionable intelligence from a newsletter article.

The author is an original thinker — extract their specific positions, frameworks, and calls. This is already edited and concise, so go deep on the substance.

WRITING STYLE — Smart Brevity:
- Lead with the most important words. Max 2 sentences per point.
- Be specific: name numbers, tickers, platforms. No hedging.
- Every content hook headline should work as a standalone scroll-stopper.

Extract ALL of these:

1. **Company Mentions**: Ticker if public. Sentiment. 1-2 sentence thesis.
2. **Macro Calls**: Specific macro/market call in one sentence.
3. **Content Hooks**: Scroll-stopping ideas. Headline + one-sentence insight. Assign content_pillar: luxury_brand | ai_business | founder_mindset | marketing_innovation | creator_economy.
4. **Marketing Tactics**: Platform, numbers, and application. (Only if relevant.)
5. **People Mentioned**: Notable people and context.
6. **Contrarian Takes**: Where the author disagrees with consensus. Highest signal.
7. **why_it_matters**: One punchy sentence.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "both",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [{{"name": "string", "ticker": "string|null", "sentiment": "bullish|bearish|neutral|mixed", "thesis": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "macro_calls": [{{"theme": "string", "position": "string", "speaker": "string|null", "context_quote": "string", "approximate_location": "early|middle|late"}}],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "context_quote": "string", "why_it_matters": "string"}}],
  "marketing_tactics": [{{"tactic": "string", "platform": "string|null", "result_cited": "string|null", "applicable_to": "string", "speaker": "string|null", "context_quote": "string"}}],
  "people_mentioned": [{{"name": "string", "context": "string", "sentiment": "string"}}],
  "contrarian_takes": ["string"],
  "why_it_matters_mark": "string|null",
  "why_it_matters_brooke": "string|null"
}}

NEWSLETTER: {podcast_name}
ARTICLE: {episode_title}
ITEM ID: {episode_id}

ARTICLE TEXT:
{transcript}"""


X_THREAD_ANALYSIS_PROMPT = """You are an expert analyst extracting intelligence from X/Twitter posts and threads.

These are short-form — prioritize contrarian takes, original frameworks, quick theses, and content hooks. Most tweets won't have company mentions or macro calls, and that's fine. Focus on what IS there.

WRITING STYLE — Smart Brevity. Be direct. One idea per point.

Extract what's present (skip empty sections):

1. **Companies**: Only if specifically discussed with a thesis.
2. **Macro Calls**: Only if a specific market/economic call is made.
3. **Content Hooks**: The tweet itself may BE the hook. Reframe as a headline.
4. **Contrarian Takes**: Where the author pushes back on consensus. Highest priority.
5. **People Mentioned**: If they tag or reference notable people.
6. **why_it_matters**: One sentence.

Return ONLY valid JSON:
{{
  "episode_id": "{episode_id}",
  "podcast_name": "{podcast_name}",
  "episode_title": "{episode_title}",
  "audience": "both",
  "one_sentence_summary": "string",
  "topic_tags": ["string"],
  "companies": [],
  "macro_calls": [],
  "content_hooks": [{{"headline": "string", "insight": "string", "angle": "string", "content_pillar": "string", "context_quote": "string", "why_it_matters": "string"}}],
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
