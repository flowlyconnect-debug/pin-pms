(() => {
  const dataNode = document.getElementById("dashboard-data");
  if (!dataNode) return;

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (_err) {
    return;
  }
  if (!payload) return;
  const canRenderCharts = !payload.insufficient_chart_data && typeof window.Chart !== "undefined";

  const rootStyles = getComputedStyle(document.documentElement);
  const lineColor = rootStyles.getPropertyValue("--dashboard-chart-line").trim() || "#4f46e5";
  const areaColor = rootStyles.getPropertyValue("--dashboard-chart-area").trim() || "rgba(79, 70, 229, 0.18)";
  const revenueColor = rootStyles.getPropertyValue("--dashboard-chart-revenue").trim() || "#16a34a";
  const gridColor = rootStyles.getPropertyValue("--dashboard-chart-grid").trim() || "#e5e7eb";
  const textColor = rootStyles.getPropertyValue("--dashboard-chart-text").trim() || "#6b7280";

  const revenueTrend = Array.isArray(payload.trend_revenue_30d) ? payload.trend_revenue_30d : [];
  const occupancyTrend = Array.isArray(payload.trend_occupancy_30d) ? payload.trend_occupancy_30d : [];
  const occupancySparkline = occupancyTrend.map((item) => Number(item.pct || 0));
  const labels = revenueTrend.map((item) => item.date);
  const revenueValues = revenueTrend.map((item) => Number(item.value || 0));
  const occupancyValues = occupancySparkline;
  const stats = payload.stats || {};

  const statCardsHost = document.getElementById("dashboard-stat-cards");
  if (statCardsHost) {
    const incomeNow = Number(stats.income_this_month || 0);
    const incomePrev = Number(stats.income_previous_month || 0);
    const incomeTrendPct = incomePrev === 0 ? 0 : ((incomeNow - incomePrev) / incomePrev) * 100;
    const cardModels = [
      {
        label: "Käyttöaste",
        value: `${Number(stats.occupancy_percent || 0).toLocaleString("fi-FI", {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })} %`,
        trend: 0,
        meta: `Tämän hetken vieraita: ${Number(stats.current_guests || 0).toLocaleString("fi-FI")}`,
        intent: "default",
        icon: "🏨",
        sparkline: occupancySparkline,
      },
      {
        label: "Tulot tässä kuussa",
        value: stats.income_this_month_fi || "0,00 €",
        trend: Number.isFinite(incomeTrendPct) ? incomeTrendPct : 0,
        meta: `Edellinen kuukausi: ${new Intl.NumberFormat("fi-FI", {
          style: "currency",
          currency: "EUR",
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(incomePrev)}`,
        intent: "success",
        icon: "💶",
        sparkline: [],
      },
      {
        label: "Kulut tässä kuussa",
        value: stats.expenses_this_month_fi || "0,00 €",
        trend: 0,
        meta: `Avoimet saatavat: ${stats.open_receivables_fi || "0,00 €"}`,
        intent: "warning",
        icon: "🧾",
        sparkline: [],
      },
      {
        label: "Nettokassavirta",
        value: stats.net_cash_flow_this_month_fi || "0,00 €",
        trend: 0,
        meta: `Avoimet laskut: ${Number(stats.open_invoices || 0).toLocaleString("fi-FI")} · Erääntyneitä: ${Number(
          stats.overdue_invoices || 0
        ).toLocaleString("fi-FI")}`,
        intent: Number(stats.net_cash_flow_this_month || 0) < 0 ? "danger" : "success",
        icon: "📈",
        sparkline: [],
      },
    ];
    statCardsHost.innerHTML = cardModels.map(renderStatCard).join("");
  }

  document.querySelectorAll("[data-chart-skeleton]").forEach((node) => {
    node.remove();
  });

  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: textColor, maxTicksLimit: 6 }, grid: { color: gridColor } },
      y: { ticks: { color: textColor }, grid: { color: gridColor } },
    },
  };

  const revenueCanvas = document.getElementById("revenue-chart");
  if (canRenderCharts && revenueCanvas && revenueValues.length > 0) {
    new window.Chart(revenueCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [{ data: revenueValues, borderColor: revenueColor, borderWidth: 2, pointRadius: 0, tension: 0.35 }],
      },
      options: commonOptions,
    });
  }

  const occupancyCanvas = document.getElementById("occupancy-chart");
  if (canRenderCharts && occupancyCanvas && occupancyValues.length > 0) {
    new window.Chart(occupancyCanvas, {
      type: "line",
      data: {
        labels: occupancyTrend.map((item) => item.date),
        datasets: [
          {
            data: occupancyValues,
            borderColor: lineColor,
            backgroundColor: areaColor,
            fill: true,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.35,
          },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          ...commonOptions.scales,
          y: { ...commonOptions.scales.y, suggestedMin: 0, suggestedMax: 100 },
        },
      },
    });
  }
})();

function renderStatCard(model) {
  const trendValue = Number(model.trend || 0);
  const trendUp = trendValue >= 0;
  const trendArrow = trendUp ? "↗" : "↘";
  const trendClass = trendUp ? "is-up" : "is-down";
  const trendLabel = `${trendArrow} ${trendValue > 0 ? "+" : ""}${trendValue.toLocaleString("fi-FI", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}% vs. ed. kk`;
  const sparkline = Array.isArray(model.sparkline) ? model.sparkline : [];
  const sparklineSvg = sparkline.length > 1 ? renderSparkline(sparkline) : "";
  return `
    <article class="dashboard-stat-card dashboard-stat-card--${model.intent || "default"}">
      <div class="dashboard-stat-card__head">
        <p class="dashboard-stat-card__label">${escapeHtml(model.label || "")}</p>
        <span class="dashboard-stat-card__icon" aria-hidden="true">${escapeHtml(model.icon || "")}</span>
      </div>
      <p class="dashboard-stat-card__value">${escapeHtml(String(model.value || ""))}</p>
      <p class="dashboard-stat-card__trend ${trendClass}">${escapeHtml(trendLabel)}</p>
      <p class="dashboard-stat-card__meta">${escapeHtml(model.meta || "")}</p>
      ${sparklineSvg}
    </article>
  `;
}

function renderSparkline(values) {
  const width = 60;
  const height = 20;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return `
    <svg class="dashboard-stat-card__sparkline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <polygon points="0,${height} ${points} ${width},${height}" />
      <polyline points="${points}" />
    </svg>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
