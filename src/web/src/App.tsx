import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { App as AntApp } from "antd";

import { ThemeProvider } from "./contexts/ThemeContext";

import { ReportProvider } from "./contexts/ReportContext";

import MainLayout from "./layouts/MainLayout";

import BacktestsPage from "./pages/trading/BacktestsPage";

import DashboardPage from "./pages/trading/DashboardPage";

import DataSourcesPage from "./pages/trading/DataSourcesPage";

import LiveTradingPage from "./pages/trading/LiveTradingPage";
import RiskPage from "./pages/trading/RiskPage";

import StrategyPage from "./pages/trading/StrategyPage";

import RadarPage from "./pages/trading/RadarPage";

import ResearchPage from "./pages/research/ResearchPage";



export default function App() {

  return (

    <ThemeProvider>

      <AntApp>

        <ReportProvider>

          <BrowserRouter>

            <Routes>

              <Route element={<MainLayout />}>

                <Route path="/" element={<Navigate to="/trading" replace />} />

                <Route path="/dashboard" element={<Navigate to="/trading" replace />} />

                <Route path="/trading" element={<DashboardPage />} />

                <Route path="/radar" element={<RadarPage />} />

                <Route path="/data-sources" element={<DataSourcesPage />} />

                <Route path="/backtests" element={<BacktestsPage />} />

                <Route path="/live-trading" element={<LiveTradingPage />} />

                <Route path="/risk" element={<RiskPage />} />

                <Route path="/research" element={<ResearchPage />} />

                <Route path="/strategy" element={<StrategyPage />} />

                <Route path="*" element={<Navigate to="/trading" replace />} />

              </Route>

            </Routes>

          </BrowserRouter>

        </ReportProvider>

      </AntApp>

    </ThemeProvider>

  );

}


