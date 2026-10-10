from __future__ import annotations
import sys, unittest
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
import portfolio_viability_triage as pvt

class TestPortfolioViabilityTriage(unittest.TestCase):
    def test_combo_is_equal_sleeve_proxy(self):
        m=pd.DataFrame({"signal_date":["2025-01-31","2025-02-28"],"year":["2025"]*2,"regime":["up","down"],"portfolio_return":[.10,-.02],"qqq_return":[.04,-.01],"excess_vs_qqq":[.06,-.01]})
        i=pd.DataFrame({"signal_date":["2025-01-31","2025-02-28"],"year":["2025"]*2,"regime":["up","down"],"portfolio_return":[.06,.04],"qqq_return":[.04,-.01],"excess_vs_qqq":[.02,.05]})
        x=pvt.combo_proxy(m,i); self.assertTrue(np.allclose(x.portfolio_return,[.08,.01])); self.assertTrue(np.allclose(x.excess_vs_qqq,[.04,.02]))
    def test_turnover_proxy_is_jaccard_distance(self):
        x=pd.DataFrame({"signal_date":["a","b","c"],"symbol_set":[frozenset("ABC"),frozenset("BCD"),frozenset("CDE")]})
        self.assertAlmostEqual(pvt.set_stats(x)["turnover_proxy"],.5)
    def test_top_year_removal_stays_explicit(self):
        x=pd.DataFrame({"signal_date":["2023-a","2024-a","2025-a"],"year":["2023","2024","2025"],"regime":["up","down","up"],"portfolio_return":[.08,.07,.30],"qqq_return":[.05,.05,.10],"excess_vs_qqq":[.03,.02,.20]})
        r=pvt.return_stats(x); self.assertEqual(r["top_year"],"2025"); self.assertAlmostEqual(r["avg_excess_without_top_year"],.025); self.assertGreater(r["loo_avg_excess_min"],0)
    def test_jaccard(self):
        self.assertAlmostEqual(pvt.jaccard(frozenset("ABC"),frozenset("BCD")),.5)
if __name__=="__main__": unittest.main()
