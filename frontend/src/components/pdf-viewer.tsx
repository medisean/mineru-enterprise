"use client";
/**
 * PDF viewer component using react-pdf.
 * Separated from the main page to avoid SSR issues with pdfjs-dist.
 */
import { useState, useEffect } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { Loader2, AlertCircle } from "lucide-react";

// Configure pdf.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  url: string;
  zoom: number;
}

export default function PdfViewer({ url, zoom }: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  };

  return (
    <div className="flex flex-col items-center gap-3">
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
            <p className="text-xs text-red-400">PDF 加载失败</p>
          </div>
        }
      >
        {Array.from({ length: numPages }, (_, i) => (
          <div key={i} className="bg-white shadow-md rounded mb-1">
            <Page
              pageNumber={i + 1}
              scale={zoom / 100}
              renderTextLayer={true}
              renderAnnotationLayer={true}
            />
          </div>
        ))}
      </Document>
    </div>
  );
}
