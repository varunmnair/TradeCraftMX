
import pandas as pd
from core.holdings import HoldingsAnalyzer
from core.session_manager import SessionManager
from core.cmp import CMPManager

class ToolRegistry:
    def __init__(self, broker):
        self.broker = broker
        self.holdings_analyzer = HoldingsAnalyzer(broker.user_id, broker.broker_name)
        session_manager = SessionManager()
        self.cmp_manager = CMPManager(csv_path="data/Name-symbol-mapping.csv", broker=broker, session_manager=session_manager)


    def get_tools(self):
        return {
            "get_portfolio_summary": self.get_portfolio_summary
        }

    def get_portfolio_summary(self, time_period: str) -> str:
        """
        Analyzes the portfolio for a given time period and returns a summary.

        Args:
            time_period (str): The time period to analyze (e.g., "last month").

        Returns:
            str: A summary of the portfolio performance.
        """
        if not self.broker:
            return "Error: Broker context is missing. Cannot execute tool."

        # The analyze_holdings method requires a broker and cmp_manager instance
        holdings = self.holdings_analyzer.analyze_holdings(self.broker, self.cmp_manager)

        if not holdings:
            return "No holdings found."

        df = pd.DataFrame(holdings)

        # Filter by time_period if necessary (this is a simplified example)
        # For a real implementation, you would parse the time_period string
        # and filter the dataframe accordingly.
        if time_period == "last month":
            # Placeholder for actual date filtering logic
            pass

        total_pnl = df["P&L"].sum()
        total_invested = df["Invested"].sum()
        roi = (total_pnl / total_invested) * 100 if total_invested > 0 else 0
        best_performer = df.loc[df["P&L"].idxmax()]
        worst_performer = df.loc[df["P&L"].idxmin()]

        summary = f"""
        Portfolio Summary for {time_period}:
        - Total P&L: {total_pnl:.2f}
        - Total Invested: {total_invested:.2f}
        - ROI: {roi:.2f}%
        - Best Performer: {best_performer['Symbol']} with P&L of {best_performer['P&L']:.2f}
        - Worst Performer: {worst_performer['Symbol']} with P&L of {worst_performer['P&L']:.2f}
        """
        return summary
