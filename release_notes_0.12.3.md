**Global Trade Goes Gold-Only**

- Foreign trades between two different factions now pay in Gold alone — never barter, never substitute goods for what the agreed price should be in coin
- A deal is sized at dispatch against the buyer's spendable Gold, and only as much Gold as the settlement can actually release (above its own Trade Reserve floor) is taken on the return leg — the seller's `paid` event records whatever Gold actually arrived
- A faction whose realm has no Mountain land, and therefore no real ongoing Gold source (Gold Ore -> Mint -> Gold), now cannot import via global trade at all — Regional Markets still works for self-trading, but inter-nation trade has always been real money
- The in-game Compendium (F1) has been updated to match: `_currency_article`'s BARTER section now scopes barter fallback to Regional Markets only, and the Foreign Trade article's CARAVAN section now describes Gold-only payment
- Trade Log and Resources tab already match: both sides now agree on what left your treasury, every turn

First time running it? Windows SmartScreen may warn about an unrecognized app - see FIRST_RUN.md in the repo.
