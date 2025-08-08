import { useMemo, useState, Suspense, lazy } from "react";
import { Stack, IconButton, Spinner } from "@fluentui/react";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import jsPDF from "jspdf";
import html2canvas from "html2canvas";

import styles from "./Answer.module.css";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../api";
import { parseAnswerToHtml } from "./AnswerParser";
import { AnswerIcon } from "./AnswerIcon";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

// Lazy load AnswerChart to avoid bundle size issues
const AnswerChart = lazy(() => import("./AnswerChart").then(module => ({ default: module.AnswerChart })));

interface Props {
    answer: ChatAppResponse;
    index: number;
    speechConfig: SpeechConfig;
    isSelected?: boolean;
    isStreaming: boolean;
    onCitationClicked: (filePath: string) => void;
    onThoughtProcessClicked: () => void;
    onSupportingContentClicked: () => void;
    onFollowupQuestionClicked?: (question: string) => void;
    showFollowupQuestions?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
}

interface StructuredResponse {
    summary: string;
    chart_data: Array<{
        label: string;
        value: number;
        source: string;
    }>;
}

export const Answer = ({
    answer,
    index,
    speechConfig,
    isSelected,
    isStreaming,
    onCitationClicked,
    onThoughtProcessClicked,
    onSupportingContentClicked,
    onFollowupQuestionClicked,
    showFollowupQuestions,
    showSpeechOutputAzure,
    showSpeechOutputBrowser
}: Props) => {
    const followupQuestions = answer.context?.followup_questions;
    const parsedAnswer = useMemo(() => parseAnswerToHtml(answer, isStreaming, onCitationClicked), [answer]);
    const { t } = useTranslation();
    const sanitizedAnswerHtml = DOMPurify.sanitize(parsedAnswer.answerHtml);
    const [copied, setCopied] = useState(false);

    // 구조화된 응답 파싱
    const structuredResponse = useMemo((): StructuredResponse | null => {
        try {
            const content = answer.message.content;
            if (typeof content === 'string' && content.trim().startsWith('{')) {
                const parsed = JSON.parse(content);
                if (parsed.summary && Array.isArray(parsed.chart_data)) {
                    return parsed as StructuredResponse;
                }
            }
        } catch (e) {
            // JSON 파싱 실패 시 null 반환
        }
        return null;
    }, [answer.message.content]);

    // 구조화된 응답인 경우 summary를 사용, 아닌 경우 기존 로직 사용
    const displayContent = structuredResponse ? structuredResponse.summary : sanitizedAnswerHtml;

    const handleCopy = () => {
        // 구조화된 응답인 경우 summary만 복사, 아닌 경우 기존 로직 사용
        const textToCopy = structuredResponse 
            ? structuredResponse.summary.replace(/<a [^>]*><sup>\d+<\/sup><\/a>|<[^>]+>/g, "")
            : sanitizedAnswerHtml.replace(/<a [^>]*><sup>\d+<\/sup><\/a>|<[^>]+>/g, "");

        navigator.clipboard
            .writeText(textToCopy)
            .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            })
            .catch(err => console.error("Failed to copy text: ", err));
    };

    const handleSavePDF = async () => {
        const reportElement = document.getElementById(`report-section-${index}`);
        if (!reportElement) {
            console.error("Report section not found");
            return;
        }

        try {
            // html2canvas를 사용하여 DOM 요소를 캔버스로 변환
            const canvas = await html2canvas(reportElement, {
                scale: 2, // 고화질을 위한 스케일
                useCORS: true,
                logging: false,
                backgroundColor: "#ffffff"
            });

            // jsPDF로 PDF 생성
            const pdf = new jsPDF({
                orientation: "portrait",
                unit: "mm",
                format: "a4"
            });

            const imgWidth = 210; // A4 너비 (mm)
            const pageHeight = 297; // A4 높이 (mm)
            const imgHeight = (canvas.height * imgWidth) / canvas.width;
            let heightLeft = imgHeight;

            const imgData = canvas.toDataURL("image/png");
            let position = 0;

            // 첫 페이지 추가
            pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
            heightLeft -= pageHeight;

            // 필요한 경우 추가 페이지 생성
            while (heightLeft >= 0) {
                position = heightLeft - imgHeight;
                pdf.addPage();
                pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
                heightLeft -= pageHeight;
            }

            // PDF 다운로드
            const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, "-");
            pdf.save(`AI-Report-${timestamp}.pdf`);
        } catch (error) {
            console.error("PDF 생성 중 오류 발생:", error);
            alert("PDF 생성 중 오류가 발생했습니다.");
        }
    };

    return (
        <Stack className={`${styles.answerContainer} ${isSelected && styles.selected}`} verticalAlign="space-between">
            <Stack.Item>
                <Stack horizontal horizontalAlign="space-between">
                    <AnswerIcon />
                    <div>
                        <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: copied ? "CheckMark" : "Copy" }}
                            title={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            ariaLabel={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            onClick={handleCopy}
                        />
                        <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: "Lightbulb" }}
                            title={t("tooltips.showThoughtProcess")}
                            ariaLabel={t("tooltips.showThoughtProcess")}
                            onClick={() => onThoughtProcessClicked()}
                            disabled={!answer.context.thoughts?.length || isStreaming}
                        />
                        <IconButton
                            style={{ color: "black" }}
                            iconProps={{ iconName: "ClipboardList" }}
                            title={t("tooltips.showSupportingContent")}
                            ariaLabel={t("tooltips.showSupportingContent")}
                            onClick={() => onSupportingContentClicked()}
                            disabled={!answer.context.data_points || isStreaming}
                        />
                        {/* PDF 저장 버튼 - 구조화된 응답이 있을 때만 표시 */}
                        {structuredResponse && (
                            <IconButton
                                style={{ color: "black" }}
                                iconProps={{ iconName: "PDF" }}
                                title="PDF로 저장"
                                ariaLabel="PDF로 저장"
                                onClick={handleSavePDF}
                                disabled={isStreaming}
                            />
                        )}
                        {showSpeechOutputAzure && (
                            <SpeechOutputAzure answer={sanitizedAnswerHtml} index={index} speechConfig={speechConfig} isStreaming={isStreaming} />
                        )}
                        {showSpeechOutputBrowser && <SpeechOutputBrowser answer={sanitizedAnswerHtml} />}
                    </div>
                </Stack>
            </Stack.Item>

            <Stack.Item grow>
                {/* PDF 저장을 위한 report-section div */}
                <div id={`report-section-${index}`} className={styles.reportSection}>
                    <div className={styles.answerText}>
                        <ReactMarkdown children={displayContent} rehypePlugins={[rehypeRaw]} remarkPlugins={[remarkGfm]} />
                    </div>

                    {/* 구조화된 응답의 차트 데이터 표시 */}
                    {structuredResponse && structuredResponse.chart_data.length > 0 && (
                        <Suspense fallback={<Spinner label="차트 로딩 중..." />}>
                            <AnswerChart chartData={structuredResponse.chart_data} title="데이터 시각화" />
                        </Suspense>
                    )}
                </div>
            </Stack.Item>

            {!!parsedAnswer.citations.length && (
                <Stack.Item>
                    <Stack horizontal wrap tokens={{ childrenGap: 5 }}>
                        <span className={styles.citationLearnMore}>{t("citationWithColon")}</span>
                        {parsedAnswer.citations.map((x, i) => {
                            const path = getCitationFilePath(x);
                            return (
                                <a key={i} className={styles.citation} title={x} onClick={() => onCitationClicked(path)}>
                                    {`${++i}. ${x}`}
                                </a>
                            );
                        })}
                    </Stack>
                </Stack.Item>
            )}

            {!!followupQuestions?.length && showFollowupQuestions && onFollowupQuestionClicked && (
                <Stack.Item>
                    <Stack horizontal wrap className={`${!!parsedAnswer.citations.length ? styles.followupQuestionsList : ""}`} tokens={{ childrenGap: 6 }}>
                        <span className={styles.followupQuestionLearnMore}>{t("followupQuestions")}</span>
                        {followupQuestions.map((x, i) => {
                            return (
                                <a key={i} className={styles.followupQuestion} title={x} onClick={() => onFollowupQuestionClicked(x)}>
                                    {`${x}`}
                                </a>
                            );
                        })}
                    </Stack>
                </Stack.Item>
            )}
        </Stack>
    );
};
