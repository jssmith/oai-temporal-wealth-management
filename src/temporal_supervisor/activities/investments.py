import json

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from common.investment_manager import InvestmentManager

class Investments:
    @staticmethod
    @activity.defn
    async def list_investments(client_id :str) -> list:
        activity.logger.info(f"Listing investments for {client_id}")
        investment_acct_mgr = InvestmentManager()
        return investment_acct_mgr.list_investment_accounts(client_id)

    @staticmethod
    @activity.defn
    async def open_investment(client_id: str, name: str, balance: float) -> dict:
        activity.logger.info(f"Opening an investment account for {client_id}, Name: {name}, Balance: {balance}")
        investment_acct_mgr = InvestmentManager()
        return investment_acct_mgr.add_investment_account(client_id, name, balance)

    @staticmethod
    @activity.defn
    async def close_investment(client_id: str, investment_id: str):
        activity.logger.info(f"Closing investment {client_id}, Investment ID: {investment_id} ")
        investment_acct_mgr = InvestmentManager()
        investment_acct_mgr.delete_investment_account(client_id, investment_id)

