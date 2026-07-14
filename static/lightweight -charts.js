document.addEventListener("DOMContentLoaded", function() {
    const container = document.getElementById('chart-container');
    if (!container) return;

    // ১. চার্ট তৈরি করা
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 250,
        layout: {
            background: { color: '#0f172a' },
            textColor: '#94a3b8',
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        timeScale: {
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // ২. ক্যান্ডেলস্টিক সিরিজ তৈরি
    const candleSeries = chart.addCandlestickSeries({
        upColor: '#00ffa3',
        downColor: '#ff3366',
        borderUpColor: '#00ffa3',
        borderDownColor: '#ff3366',
        wickUpColor: '#00ffa3',
        wickDownColor: '#ff3366',
    });

    // ৩. আপনার Flask API থেকে ক্যান্ডেল ডাটা লোড করার ফাংশন
    function loadChartData() {
        fetch('/api/candles') 
            .then(res => res.json())
            .then(data => {
                if (data && data.candles) {
                    candleSeries.setData(data.candles);
                    console.log("Firebase থেকে ক্যান্ডেল ডাটা সফলভাবে লোড হয়েছে!");
                }
            })
            .catch(err => console.error("ডাটা আনতে সমস্যা হয়েছে:", err));
    }

    loadChartData();

    // ৪. লাইট/ডার্ক মোড সুইচ করার লজিক
    const toggleBtn = document.getElementById('chart-theme-toggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            document.body.classList.toggle('light');
            const isLight = document.body.classList.contains('light');

            // বাটনের ভেতরের টেক্সট পরিবর্তন
            const status = document.getElementById('theme-status');
            if (status) status.innerText = isLight ? 'LIGHT' : 'DARK';

            // চার্টের ব্যাকগ্রাউন্ড কালার পরিবর্তন
            chart.applyOptions({
                layout: {
                    background: { color: isLight ? '#ffffff' : '#0f172a' },
                    textColor: isLight ? '#0f172a' : '#94a3b8',
                }
            });
        });
    }

    // মোবাইল স্ক্রিন ঘুরানো বা রিসাইজ হলে চার্ট ঠিক রাখার জন্য
    window.addEventListener('resize', () => {
        chart.resize(container.clientWidth, 250);
    });
});
