-- Bind timing, attempt and trace creation to an instance on the privileged side,
-- so loss of the browser/API response cannot leave a running untracked attempt.
CREATE TABLE public.instance_activations (
    challenge_id BIGINT PRIMARY KEY REFERENCES public.challenges(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    attempt_id BIGINT NOT NULL REFERENCES public.completed_challenges(id) ON DELETE CASCADE,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON public.instance_activations FROM PUBLIC;
