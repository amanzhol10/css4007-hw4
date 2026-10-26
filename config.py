"""Fixed settings shared by all three strategies (the 'controls' of the experiment)."""

MODEL = "gpt-5.6-luna"

K_SAMPLES = 5            # S2: how many times the model is asked
MAX_ROUNDS = 10          # S3: maximum number of model calls per question
TEMP_SINGLE = 0.0        # S1 and S3 (dropped automatically if the model rejects it)
TEMP_VOTE = 1.0          # S2 samples (needs variety; dropped if the model rejects it)

# Prices in USD per 1,000,000 tokens. FILL THESE IN from the OpenAI pricing page
# on the day you run (they are not known to this repository).
PRICE_INPUT_PER_M = 0.0
PRICE_OUTPUT_PER_M = 0.0
