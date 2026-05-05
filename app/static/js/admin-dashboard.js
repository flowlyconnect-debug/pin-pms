(() => {
  const dataNode = document.getElementById("dashboard-data");
  if (!dataNode) return;

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (_err) {
    return;
  }
  if (!payload || payload.insufficient_chart_data) return;
  if (typeof window.Chart === "undefined") return;

  const rootStyles = getComputedStyle(document.documentElement);
  const lineColor = rootStyles.getPropertyValue("--dashboard-chart-line").trim() || "#4f46e5";
  const areaColor = rootStyles.getPropertyValue("--dashboard-chart-area").trim() || "rgba(79, 70, 229, 0.18)";
  const revenueColor = rootStyles.getPropertyValue("--dashboard-chart-revenue").trim() || "#16a34a";
  const gridColor = rootStyles.getPropertyValue("--dashboard-chart-grid").trim() || "#e5e7eb";
  const textColor = rootStyles.getPropertyValue("--dashboard-chart-text").trim() || "#6b7280";

  const revenueTrend = Array.isArray(payload.trend_revenue_30d) ? payload.trend_revenue_30d : [];
  const occupancyTrend = Array.isArray(payload.trend_occupancy_30d) ? payload.trend_occupancy_30d : [];
  const labels = revenueTrend.map((item) => item.date);
  const revenueValues = revenueTrend.map((item) => Number(item.value || 0));
  const occupancyValues = occupancyTrend.map((item) => Number(item.pct || 0));

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
  if (revenueCanvas && revenueValues.length > 0) {
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
  if (occupancyCanvas && occupancyValues.length > 0) {
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
