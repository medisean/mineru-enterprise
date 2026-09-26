"use client";
/**
 * PDF viewer component using react-pdf.
 * Separated from the main page to avoid SSR issues with pdfjs-dist.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { Loader2, AlertCircle } from "lucide-react";
import { useT } from "@/lib/i18n/use-translation";

// Configure pdf.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  url: string;
  zoom: number;
}

interface PageMetrics {
  width: number;
  height: number;
}

interface LazyPdfPageProps {
  pageNumber: number;
  pageWidth: number;
  estimatedHeight: number;
  onMeasure: (pageNumber: number, metrics: PageMetrics) => void;
}

const PAGE_ASPECT_RATIO = 1.414;
const PAGE_BUFFER_PX = 1200;

function LazyPdfPage({
  pageNumber,
  pageWidth,
  estimatedHeight,
  onMeasure,
}: LazyPdfPageProps) {
  const pageRef = useRef<HTMLDivElement>(null);
  const [isNearViewport, setIsNearViewport] = useState(false);

  useEffect(() => {
    const element = pageRef.current;
    if (!element || typeof IntersectionObserver === "undefined") {
      setIsNearViewport(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => setIsNearViewport(entry.isIntersecting),
      { rootMargin: `${PAGE_BUFFER_PX}px 0px` },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const handleLoadSuccess = useCallback(
    (page: PageMetrics) => onMeasure(pageNumber, page),
    [onMeasure, pageNumber],
  );

  return (
    <div
      ref={pageRef}
      data-pdf-page={pageNumber}
      className="bg-white shadow-md rounded mb-1"
      style={{
        width: pageWidth || "100%",
        height: estimatedHeight,
      }}
      aria-label={`PDF page ${pageNumber}`}
    >
      {isNearViewport && pageWidth > 0 ? (
        <Page
          pageNumber={pageNumber}
          width={pageWidth}
          renderTextLayer={true}
          renderAnnotationLayer={true}
          onLoadSuccess={handleLoadSuccess}
        />
      ) : null}
    </div>
  );
}

export default function PdfViewer({ url, zoom }: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [containerWidth, setContainerWidth] = useState(0);
  const [pageRatios, setPageRatios] = useState<Record<number, number>>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const t = useT();

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const updateWidth = () => setContainerWidth(element.clientWidth);
    updateWidth();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateWidth);
      return () => window.removeEventListener("resize", updateWidth);
    }

    const observer = new ResizeObserver(updateWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  };

  const onPageMeasure = useCallback((pageNumber: number, metrics: PageMetrics) => {
    if (!metrics.width || !metrics.height) return;
    setPageRatios((current) => {
      const ratio = metrics.height / metrics.width;
      if (current[pageNumber] === ratio) return current;
      return { ...current, [pageNumber]: ratio };
    });
  }, []);

  const pageWidth = containerWidth
    ? Math.max(240, Math.floor((containerWidth * zoom) / 100))
    : 0;

  return (
    <div ref={containerRef} className="flex w-full flex-col items-center gap-3">
      <Document
        file={url}
        onLoadSuccess={onDocumentLoadSuccess}
        loading={
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          </div>
        }
        error={
          <div className="text-center py-20">
            <AlertCircle className="mx-auto h-8 w-8 text-red-300 mb-2" />
            <p className="text-xs text-red-400">{t("pdf.loadFailed")}</p>
          </div>
        }
      >
        {Array.from({ length: numPages }, (_, i) => (
          <LazyPdfPage
            key={i + 1}
            pageNumber={i + 1}
            pageWidth={pageWidth}
            estimatedHeight={Math.max(
              160,
              Math.ceil((pageWidth || 480) * (pageRatios[i + 1] || PAGE_ASPECT_RATIO)),
            )}
            onMeasure={onPageMeasure}
          />
        ))}
      </Document>
    </div>
  );
}
