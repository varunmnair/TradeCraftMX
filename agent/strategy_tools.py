from typing import List
import core.cli as cli
import pandas as pd
from core.multilevel_entry import MultiLevelEntryStrategy
from core.gtt_manage import GTTManager

class StrategyTools:
    def __init__(self):
        self.session = self._get_session()
        # Initialize Baseline and Working Plan
        self.baseline_plan = self.session.read_gtt_plan() or []
        self.working_plan = list(self.baseline_plan) # Shallow copy
        self.history_stack = [] # To store previous states of working_plan

    def get_definitions(self):
        return [
            {
                "name": "filter_by_query",
                "args": "query: str",
                "desc": "Filter plan using pandas query syntax (e.g., \"entry == 'E1'\", \"price < 500\", \"(price - ltp)/ltp > 0.05\")."
            },
            {
                "name": "undo_last_action",
                "args": "",
                "desc": "Revert to previous plan state."
            },
            {
                "name": "reset_to_baseline",
                "args": "",
                "desc": "Reload original plan."
            },
            {
                "name": "apply_risk_management",
                "args": "",
                "desc": "Apply risk rules."
            },
            {
                "name": "show_plan",
                "args": "",
                "desc": "Print the current plan table to the console."
            },
            {
                "name": "place_orders",
                "args": "",
                "desc": "Execute the plan (Final Action)."
            }
        ]

    def _get_session(self):
        if not cli.current_session:
            raise ValueError("Session not initialized.")
        return cli.current_session

    def get_working_plan(self):
        """Returns the current working plan."""
        return self.working_plan

    def get_plan_stats(self):
        """Returns a summary of the current working plan."""
        if not self.working_plan:
            return "Plan is empty."
        
        df = pd.DataFrame(self.working_plan)
        stats = f"Total Orders: {len(df)}"
        if 'entry' in df.columns:
            stats += f" | By Entry: {df['entry'].value_counts().to_dict()}"
        return stats

    def reset_to_baseline(self):
        """Resets the working plan to the original baseline."""
        self.working_plan = list(self.baseline_plan)
        self.history_stack = []
        return f"Reset plan to baseline ({len(self.working_plan)} orders)."

    def undo_last_action(self):
        """Reverts the working plan to the previous state."""
        if not self.history_stack:
            return "Nothing to undo. At baseline."
        
        self.working_plan = self.history_stack.pop()
        return f"Undid last action. Plan now has {len(self.working_plan)} orders."

    def filter_by_query(self, query: str):
        """
        Filters the working plan using a pandas query string.
        Args:
            query: A pandas query string (e.g., "entry == 'E1' and price < 500").
        """
        if not self.working_plan:
            return "Plan is empty."
        
        # Save state before modifying
        self.history_stack.append(list(self.working_plan))
        
        try:
            df = pd.DataFrame(self.working_plan)
            filtered_df = df.query(query)
            
            if filtered_df.empty:
                # Auto-revert if result is empty to avoid dead-ends
                self.working_plan = self.history_stack.pop()
                return "Filter resulted in 0 orders. Reverted to previous state."
            
            self.working_plan = filtered_df.to_dict('records')
            return f"Filtered by '{query}'. Retained {len(self.working_plan)} orders."
        except Exception as e:
            self.working_plan = self.history_stack.pop() # Revert on error
            return f"Error in filter query: {e}. Plan unchanged."

    def apply_risk_management(self):
        """Applies risk management rules to the current draft plan."""
        if not self.working_plan:
            return "No draft plan found."

        # Save state
        self.history_stack.append(list(self.working_plan))

        planner = MultiLevelEntryStrategy(
            broker=self.session.broker,
            cmp_manager=self.session.get_cmp_manager(),
            holdings=self.session.get_holdings(),
            entry_levels=self.session.get_entry_levels(),
            gtt_cache=self.session.get_gtt_cache()
        )

        self.working_plan = planner.apply_risk_to_plan(self.working_plan)
        return f"Risk management applied. Plan now has {len(self.working_plan)} orders."

    def show_plan(self):
        """Returns a tabular string of the current working plan."""
        if not self.working_plan:
            return "Plan is empty."
        
        df = pd.DataFrame(self.working_plan)
        # Select relevant columns for display
        desired_cols = ['symbol', 'ltp', 'price', 'trigger', 'qty', 'entry', 'risk_adj']
        cols = [c for c in desired_cols if c in df.columns]
        
        return "\n" + df[cols].to_string(index=False)

    def place_orders(self):
        """Places the GTT orders from the current draft plan."""
        if not self.working_plan:
            return "No orders to place."

        # Commit working plan to session before placing
        self.session.write_gtt_plan(self.working_plan)

        manager = GTTManager(self.session.broker, self.session.get_cmp_manager(), self.session)
        placed_orders = manager.place_orders(self.working_plan, dry_run=False)
        
        # Clear plan after placement
        self.session.delete_gtt_plan()
        self.working_plan = []
        self.baseline_plan = []
        
        if not placed_orders:
            return "No orders were placed."

        # Create detailed result table
        df = pd.DataFrame(placed_orders)
        desired_cols = ['symbol', 'entry', 'qty', 'trigger', 'status', 'message']
        cols = [c for c in desired_cols if c in df.columns]
        
        success_count = len([o for o in placed_orders if o.get('status') == 'Success'])
        return f"Placed {len(placed_orders)} orders ({success_count} successful).\n\n{df[cols].to_string(index=False)}"