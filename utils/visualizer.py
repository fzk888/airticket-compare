"""数据可视化工具"""
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非GUI后端
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']  # 中文字体
plt.rcParams['axes.unicode_minus'] = False  # 负号显示

class Visualizer:
    """价格对比可视化"""

    @staticmethod
    def create_price_chart(results: list, output_path: str = "price_comparison.png"):
        """生成价格对比柱状图"""
        platforms = []
        prices = []
        colors = []

        for result in results:
            if result.get("status") == "success":
                platforms.append(result["platform"])
                prices.append(result["lowest_price"])
                colors.append("#4CAF50")
            else:
                platforms.append(result["platform"])
                prices.append(0)
                colors.append("#F44336")

        if not prices or all(p == 0 for p in prices):
            return None

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(platforms, prices, color=colors, alpha=0.8)

        # 标注价格
        for bar, price in zip(bars, prices):
            if price > 0:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'¥{price}', ha='center', va='bottom', fontsize=12)

        ax.set_ylabel('价格 (CNY)', fontsize=12)
        ax.set_title('机票价格对比', fontsize=14, fontweight='bold')
        ax.grid(axis='y', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        return output_path
