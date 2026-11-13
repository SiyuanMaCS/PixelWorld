# Retry accounting

The default cap is five total model attempts per case. Token budget exhaustion,
ending without a submission and an invalid submission consume a model attempt.
Only positively identified infrastructure interruptions are exempt: for example,
a recorded provider queue/connection error or `validation.infra_error`. Unknown
failures are counted conservatively rather than allowing unbounded retries.

Run directory ordinals are permanent record IDs. Two infrastructure records
followed by five model attempts can therefore produce seven directories. All
existing directories, successful submissions, token usage and retry ledgers are
retained. A new authorization starts after the highest existing directory ID;
there is no renumbering or moving failure records to make room for retries.

`--max-total-attempts 5` controls model attempts directly. It is not translated
into three authorization rounds. `--max-rounds` remains a legacy explicit option
and has no default effect. The watcher preserves the existing token budget and
its recorded authorization-window accounting.

Historical attempts already authorized under earlier limits remain available.
Lowering a cap prevents new launches after the model-attempt limit is reached;
it does not hide a previously validated successful submission.
