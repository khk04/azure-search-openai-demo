import React from "react";
import { Stack, Text } from "@fluentui/react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import styles from "./AnswerChart.module.css";

interface ChartDataPoint {
    label: string;
    value: number;
    source: string;
}

interface Props {
    chartData: ChartDataPoint[];
    title?: string;
    chartType?: "bar" | "pie";
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d'];

export const AnswerChart: React.FC<Props> = ({ chartData, title, chartType = "bar" }) => {
    if (!chartData || chartData.length === 0) {
        return null;
    }

    // 차트 데이터 변환
    const transformedData = chartData.map(item => ({
        name: item.label,
        value: item.value,
        source: item.source
    }));

    const renderBarChart = () => (
        <ResponsiveContainer width="100%" height={300}>
            <BarChart data={transformedData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis 
                    dataKey="name" 
                    angle={-45}
                    textAnchor="end"
                    height={60}
                    fontSize={12}
                />
                <YAxis fontSize={12} />
                <Tooltip 
                    formatter={(value, name, props) => [
                        `${Number(value).toLocaleString()}`,
                        name,
                        `출처: ${props.payload?.source || 'N/A'}`
                    ]}
                />
                <Legend />
                <Bar dataKey="value" fill="#0078d4" name="값" />
            </BarChart>
        </ResponsiveContainer>
    );

    const renderPieChart = () => (
        <ResponsiveContainer width="100%" height={300}>
            <PieChart>
                <Pie
                    data={transformedData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name} (${((percent || 0) * 100).toFixed(1)}%)`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                >
                    {transformedData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                </Pie>
                <Tooltip 
                    formatter={(value, name, props) => [
                        `${Number(value).toLocaleString()}`,
                        name,
                        `출처: ${props.payload?.source || 'N/A'}`
                    ]}
                />
                <Legend />
            </PieChart>
        </ResponsiveContainer>
    );

    // 최적 차트 타입 자동 결정
    const getOptimalChartType = (): "bar" | "pie" => {
        if (chartType !== "bar") return chartType;
        
        // 데이터가 5개 이하이고 비율을 나타낼 때는 파이 차트가 더 적합
        if (chartData.length <= 5 && chartData.every(item => item.value > 0)) {
            const total = chartData.reduce((sum, item) => sum + item.value, 0);
            const maxValue = Math.max(...chartData.map(item => item.value));
            // 최대값이 전체의 90% 이상이 아닐 때 파이 차트 추천
            if (maxValue / total < 0.9) {
                return "pie";
            }
        }
        
        return "bar";
    };

    const optimalChartType = getOptimalChartType();

    return (
        <Stack className={styles.chartContainer}>
            {title && (
                <Text variant="mediumPlus" className={styles.chartTitle}>
                    📊 {title}
                </Text>
            )}
            <div className={styles.chartWrapper}>
                {optimalChartType === "pie" ? renderPieChart() : renderBarChart()}
            </div>
            <div className={styles.chartSources}>
                <Text variant="small" className={styles.sourceText}>
                    출처: {[...new Set(chartData.map(item => item.source))].join(", ")}
                </Text>
            </div>
        </Stack>
    );
};