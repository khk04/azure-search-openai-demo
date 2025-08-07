import React, { Component, ErrorInfo, ReactNode } from 'react';
import { MessageBar, MessageBarType, Stack, DefaultButton } from '@fluentui/react';

interface Props {
    children: ReactNode;
    fallback?: ReactNode;
}

interface State {
    hasError: boolean;
    error?: Error;
    errorInfo?: ErrorInfo;
}

export class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error('ErrorBoundary caught an error:', error, errorInfo);
        this.setState({ error, errorInfo });
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: undefined, errorInfo: undefined });
        // Force a page reload to clear any stale modules
        window.location.reload();
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) {
                return this.props.fallback;
            }

            return (
                <Stack tokens={{ childrenGap: 20 }} styles={{ root: { padding: 20 } }}>
                    <MessageBar messageBarType={MessageBarType.error}>
                        <strong>애플리케이션 오류가 발생했습니다</strong>
                    </MessageBar>
                    
                    <div>
                        <p>페이지를 로드하는 중에 오류가 발생했습니다. 이는 보통 다음과 같은 경우에 발생합니다:</p>
                        <ul>
                            <li>네트워크 연결 문제</li>
                            <li>브라우저 캐시 문제</li>
                            <li>애플리케이션 업데이트 중</li>
                        </ul>
                    </div>

                    <DefaultButton 
                        text="페이지 새로고침" 
                        onClick={this.handleRetry}
                        primary
                    />

                    {import.meta.env.DEV && this.state.error && (
                        <details style={{ marginTop: 20 }}>
                            <summary>오류 세부 정보 (개발 모드)</summary>
                            <pre style={{ 
                                background: '#f5f5f5', 
                                padding: 10, 
                                overflow: 'auto',
                                fontSize: '12px'
                            }}>
                                {this.state.error.toString()}
                                {this.state.errorInfo?.componentStack}
                            </pre>
                        </details>
                    )}
                </Stack>
            );
        }

        return this.props.children;
    }
}