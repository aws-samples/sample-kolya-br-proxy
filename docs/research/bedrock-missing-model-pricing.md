# Missing Bedrock pricing for three production model IDs

Research date: 2026-09-27 (UTC)

## Executive conclusion

AWS officially documents all three production IDs. They are not separate foundation models: they are AWS system-defined cross-Region inference profile IDs for the base models `openai.gpt-6-sol`, `xai.grok-4.6`, and `openai.gpt-6-astra`. AWS also publishes official Standard-tier token prices for all three.

A pricing lookup should therefore normalize the profile ID to the base model **for model and offer discovery**, but retain the profile scope (`global` versus `us`/Geo) **when selecting the price row**. Stripping the prefix and applying one universal base rate is unsafe because AWS publishes different Global CRIS and Geo/In-Region rates.

All prices below are USD per 1 million tokens.

## Findings by production model ID

### `global.openai.gpt-6-sol`

- **Officially documented:** Yes. The AWS model card lists the base ID `openai.gpt-6-sol`, Geo profile `us.openai.gpt-6-sol`, and Global profile `global.openai.gpt-6-sol`. On `bedrock-runtime`, the profile is required; the base model is not available for in-Region calls. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-sol.html)
- **Identity mapping:** `global.openai.gpt-6-sol` -> base model `openai.gpt-6-sol`; select the **Global CRIS** rate.
- **Official Global CRIS prices:**

| Context | Input | Cache write | Cache read | Output |
|---|---:|---:|---:|---:|
| Short (272K input tokens or fewer) | $2.00 | $2.50 | $0.20 | $10.00 |
| Long (more than 272K input tokens) | $4.00 | $5.00 | $0.40 | $15.00 |

AWS states that when input exceeds 272,000 tokens, the long-context rates apply to the full request. The card says the model supports only the Standard service tier. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-sol.html)

OpenAI's own model page corroborates the short-context first-party rates ($2.00 input, $2.50 cache write, $0.20 cached input, $10.00 output), but the AWS model card is the authority for Bedrock profile pricing. [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-6-sol)

### `global.xai.grok-4.6`

- **Officially documented:** Yes. The AWS model card lists base ID `xai.grok-4.6`, Geo profile `us.xai.grok-4.6`, and Global profile `global.xai.grok-4.6`. On `bedrock-runtime`, the profile is required. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-xai-grok-4-6.html)
- **Identity mapping:** `global.xai.grok-4.6` -> base model `xai.grok-4.6`; select the **Global CRIS** rate.
- **Official Global CRIS Standard prices:** input **$2.00**, cache read **$0.50**, output **$6.00**.
- **Cache-write price:** AWS does not publish a separate cache-write dimension in this model's table; it publishes only input, output, and cache read. Do not synthesize a cache-write rate.

The AWS card also gives In-Region/Geo Standard prices of $2.20 input, $0.55 cache read, and $6.60 output. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-xai-grok-4-6.html)

xAI independently confirms that Grok 4.6 on Amazon Bedrock is $2.00 input, $0.50 cached input, and $6.00 output per million tokens. [xAI Bedrock announcement](https://x.ai/news/grok-4-6-amazon-bedrock)

### `us.openai.gpt-6-astra`

- **Officially documented:** Yes. The AWS model card lists base ID `openai.gpt-6-astra`, Geo profile `us.openai.gpt-6-astra`, and Global profile `global.openai.gpt-6-astra`. On `bedrock-runtime`, the base model is not available for in-Region calls. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html)
- **Identity mapping:** `us.openai.gpt-6-astra` -> base model `openai.gpt-6-astra`; select the **Geo CRIS** rate, not Global CRIS.
- **Official Geo CRIS prices:**

| AWS table | Input | 30-minute cache write | Cache read | Output |
|---|---:|---:|---:|---:|
| Short Context Window (272K) | $11.00 | $13.75 | $1.10 | $55.00 |
| Long Context Window (1.05M) | $22.00 | $27.50 | $2.20 | $82.50 |

AWS says these are Standard-tier prices and that Priority and Flex are not supported. [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html)

OpenAI's model page corroborates the first-party Global/base short-context rates ($10.00 input, $1.00 cached input, $50.00 output); the 10% higher Geo CRIS values above are the applicable Bedrock prices for the production `us.` profile. [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-6-astra)

## Official mechanisms for obtaining pricing

### 1. Bedrock pricing page and model cards

Start with the [Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) and the model-specific AWS cards linked above. The cards are currently the clearest authoritative source because they identify the base model and profile IDs and show profile-specific input, output, and cache rates.

AWS states that Price List Query/Bulk data is informational and, if it differs from a service pricing page, AWS charges the service-page price. [AWS Price List overview](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)

### 2. AWS Price List Query API / `GetProducts`

Use the following discovery sequence rather than hard-coding undocumented attribute names:

1. `DescribeServices` to discover relevant service codes and attributes.
2. `GetAttributeValues` to inspect values for attributes such as `model`, `usagetype`, `location`, and `operation`.
3. `GetProducts` with `ServiceCode=AmazonBedrock` and exact base-model filters. All supplied filters are ANDed. [`GetProducts`](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html), [`Filter`](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_Filter.html), [`GetAttributeValues`](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetAttributeValues.html)

Example starting point:

```bash
aws pricing get-products \
  --service-code AmazonBedrock \
  --filters Type=TERM_MATCH,Field=model,Value=xai.grok-4.6 \
  --region us-east-1
```

Then select the `usagetype`/price dimension matching Global or Geo, Standard, and input/output/cache usage. Query by the **base** model value, not the inference-profile ID.

The public Bulk API is also usable without interpreting `GetProducts` pagination. Discover the service and then inspect current JSON/CSV products and `terms.OnDemand` price dimensions. [Bulk API workflow](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api.html), [finding prices in a price-list file](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/finding-prices-in-service-price-list-files.html), [current `AmazonBedrock` JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/index.json)

Snapshot on 2026-09-27: the current `AmazonBedrock` public file contains exact `model=xai.grok-4.6` dimensions, including Global Standard rates of $0.002/$0.0005/$0.006 per 1K input/cache-read/output tokens. Exact GPT-6 Sol/Astra model names and their AWS Marketplace product IDs were absent from the current `AmazonBedrock`, `AmazonBedrockFoundationModels`, and `AmazonBedrockService` files. This demonstrates catalog lag/coverage differences, not absence of an official price; use the AWS model cards or authenticated offer API when the Price List API has no row.

### 3. AWS Pricing Calculator

Use [AWS Pricing Calculator](https://calculator.aws/) to add Amazon Bedrock and model expected token volumes when the desired model/profile is available. It is useful for scenario estimates, not as a billing authority. AWS documents that calculator prices come from the AWS Price List API and that calculator output is only an estimate. [Calculator documentation](https://docs.aws.amazon.com/pricing-calculator/latest/userguide/what-is-pricing-calculator.html)

Consequently, a newly launched model omitted from Price List data may also be missing from Calculator; Calculator cannot repair that gap.

### 4. Bedrock / AWS Marketplace offer and product APIs

For an account-aware rate card (including private offers), call Bedrock's `ListFoundationModelAgreementOffers` with the **base model ID**, for example:

```bash
aws bedrock list-foundation-model-agreement-offers \
  --model-id openai.gpt-6-sol \
  --offer-type ALL
```

Its response contains `termDetails.usageBasedPricingTerm.rateCard[]`, including `description`, `dimension`, `price`, and `unit`. [`ListFoundationModelAgreementOffers`](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html)

The OpenAI AWS model cards expose Marketplace product IDs:

- GPT-6 Sol: `prod-zpwu74hhojefo`
- GPT-6 Astra: `prod-hqau7gqhlqsrg`

For AWS Marketplace Discovery, use `GetProduct` for product metadata, `ListPurchaseOptions` filtered by product ID to obtain an offer ID, `GetOffer` for the pricing model, and `GetOfferTerms` for the actual usage-based/private pricing terms. [`GetProduct`](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-discovery_GetProduct.html), [`ListPurchaseOptions`](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-discovery_ListPurchaseOptions.html), [`GetOffer`](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-discovery_GetOffer.html), [`GetOfferTerms`](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-discovery_GetOfferTerms.html)

The Grok 4.6 AWS card does not publish a Marketplace product ID, so start with the Bedrock agreement-offers API using `xai.grok-4.6` or discover it through the Bedrock model catalog rather than guessing a product ID.

### 5. CUR / CUR 2.0

CUR is a retrospective billing source, not a pre-use price catalog. AWS says CUR contains a line item for each unique combination of AWS product, usage type, and operation **that the account used**. Therefore, before first usage there is no model-specific line item from which CUR can supply a rate. [What is CUR](https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html)

After usage appears, CUR can provide:

- `line_item_usage_amount`, `line_item_unblended_rate`, and `line_item_unblended_cost` (cost is rate multiplied by usage); [line-item columns](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2-line-item.html)
- `pricing_public_on_demand_rate` for that line item; [pricing columns](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2-pricing.html)
- Bedrock-specific `product.model`, `product.provider`, and `product.inference_type` values for grouping model and token-type costs. [product columns](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2-product.html)

CUR can therefore validate and reconcile an **observed billed/effective rate after usage**, subject to units, discounts, credits, and private terms. It cannot answer the prospective "what will the first token cost?" question by itself.

## Safest fallback when no official price is available

For a prepaid or balance-enforcing proxy, fail closed:

1. Mark the model/profile as **price unavailable** and disable billable production invocation until an official profile-specific rate is recorded.
2. Never treat a missing price as zero, never fuzzy-match a similarly named model, and never substitute the provider's direct-API price for an AWS Geo/Global profile.
3. Require a versioned operator override backed by an AWS pricing page/model card or the account's offer rate card; preserve context thresholds, service tier, cache dimensions, currency, unit, effective date, and source URL.
4. Use CUR only for post-use reconciliation, not to authorize first use.

For the three IDs in this report, an unknown-price fallback is unnecessary: actual official AWS price numbers were found for all three, with the caveat that Grok 4.6 has no separately published cache-write rate.
