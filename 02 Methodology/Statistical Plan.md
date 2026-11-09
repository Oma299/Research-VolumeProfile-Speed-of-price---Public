# Statistical Plan (Pilot v0.1)

## Primary Relationship & Survival Analysis

- **Primary exposure:** непрерывная переменная $\log(1 + VA)$.
- **Primary outcome:** время до достижения цели $1 \times \text{ATR}$ (до 240 минут).
- Для анализа времени до события (time-to-target) учитывается right censoring.
- В качестве предварительной основной модели полного исследования рассматривается **Cox proportional hazards model**, при этом:
  - обязательно проверяется выполнение assumption пропорциональных рисков (proportional hazards assumption);
  - модель не представляется как подтверждённая заранее;
  - Kaplan–Meier curves по квинтилям используются как описательная визуализация.

## Key Secondary Outcome

- Моделирование directional return через 60 минут ($R_{60}$) относительно $\log(1 + VA)$ с указанием effect size и confidence interval.

## Controls

Контрольные переменные в регрессионных моделях:
1. Volatility ($\text{ATR}[t-1] / \text{Close}[t-1]$)
2. Normalized box width ($(H - L) / \text{ATR}[t-1]$)
3. Breakout strength
4. Pre-breakout trend (`PreTrend` = подписанная доходность за предыдущие 32 свечи)
5. Breakout direction (`breakout_direction`)
6. Hour of day UTC (`hour_of_day_utc`)

## Dependency & Standard Errors

- Ближние события могут быть зависимы. Предусматривается использование block bootstrap по календарным дням/неделям или cluster-robust standard errors. Случайное разделение train/test (random split) не выполняется.
- В полном исследовании train/validation/test разделяются по времени с embargo не менее 30 календарных дней, квантили VA определяются строго на train.

## Multiple Testing

- Primary hypothesis анализируется отдельно. Secondary/exploratory outcomes маркируются явно. Для семейства дополнительных тестов применяется поправка Холма (Holm correction) или Benjamini–Hochberg FDR.

See [[02 Methodology/Research Protocol|Research Protocol]].
