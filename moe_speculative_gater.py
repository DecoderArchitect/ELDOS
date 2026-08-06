import torch


class CUDAStatefulSpecGater:
    """
    Drop-in speculative depth gater for reasoning LLMs.
    Switches between k=1 and k=2 without invalidating pre-captured CUDA graphs.
    """

    def __init__(
        self,
        think_start_id: int,
        think_end_id: int,
        ema_decay: float = 0.85,
        alpha_threshold: float = 0.45,
    ):
        self.think_start_id = think_start_id
        self.think_end_id = think_end_id
        self.ema_decay = ema_decay
        self.alpha_threshold = alpha_threshold

        # Internal state (kept lightweight for zero-overhead loop execution)
        self.in_reasoning_block = False
        self.ema_alpha = 0.80

    @torch.inference_mode()
    def step(self, last_token_id: int, current_acceptance_rate: float) -> int:
        """
        Returns target graph index: 1 (for k=1 shallow speculation) or 2 (for k=2 deep speculation).
        """
        # 1. State invariant check: track Chain-of-Thought boundaries
        if last_token_id == self.think_start_id:
            self.in_reasoning_block = True
        elif last_token_id == self.think_end_id:
            self.in_reasoning_block = False

        # 2. Smooth EMA update to prevent graph-switching oscillation
        self.ema_alpha = (self.ema_decay * self.ema_alpha) + (
            (1.0 - self.ema_decay) * current_acceptance_rate
        )

        # 3. Deterministic execution routing
        # Force k=1 inside reasoning blocks OR when EMA acceptance collapses
        if self.in_reasoning_block or self.ema_alpha < self.alpha_threshold:
            return 1  # Route to pre-captured k=1 graph (saves memory bus bandwidth)
        else:
            return 2  # Route to pre-captured k=2 graph (exploits high locality)


if __name__ == "__main__":
    # Synthetic verification test
    THINK_START = 151648  # Example <think> start token ID
    THINK_END = 151649    # Example </think> end token ID

    gater = CUDAStatefulSpecGater(think_start_id=THINK_START, think_end_id=THINK_END)

    print("--- CUDAStatefulSpecGater Verification Test ---")
    print("Normal generation (alpha=0.85) -> Target Graph k =", gater.step(100, 0.85))
    print("Encounter <think> token       -> Target Graph k =", gater.step(THINK_START, 0.85))
    print("Inside reasoning block         -> Target Graph k =", gater.step(200, 0.85))
    print("Encounter </think> token        -> Target Graph k =", gater.step(THINK_END, 0.85))
    print("Post-reasoning (alpha=0.85)   -> Target Graph k =", gater.step(300, 0.85))
    print("Acceptance collapse (alpha=0.20)-> Target Graph k =", gater.step(301, 0.20))
