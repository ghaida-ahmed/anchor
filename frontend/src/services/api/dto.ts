/**
 * Wire types and their mapping into domain types.
 *
 * The API speaks snake_case; the app speaks camelCase. Translating in one place
 * means a backend field rename is a one-file change, and components never see the
 * transport format.
 */

import type {
  Course,
  CourseDocument,
  DocumentFileType,
  ISODateString,
  ProcessingStatus,
  User,
} from '@/types/domain';

export interface UserDto {
  id: string;
  name: string;
  email: string;
  timezone: string;
  created_at: ISODateString;
}

export interface CourseDto {
  id: string;
  user_id: string;
  title: string;
  code: string;
  description: string;
  document_count: number;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface DocumentDto {
  id: string;
  course_id: string;
  filename: string;
  original_filename: string;
  file_type: DocumentFileType;
  file_size: number;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface TokenDto {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export function toUser(dto: UserDto): User {
  return {
    id: dto.id,
    name: dto.name,
    email: dto.email,
    timezone: dto.timezone,
    createdAt: dto.created_at,
  };
}

export function toCourse(dto: CourseDto): Course {
  return {
    id: dto.id,
    userId: dto.user_id,
    title: dto.title,
    code: dto.code,
    description: dto.description,
    documentCount: dto.document_count,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

export function toDocument(dto: DocumentDto): CourseDocument {
  return {
    id: dto.id,
    courseId: dto.course_id,
    filename: dto.filename,
    originalFilename: dto.original_filename,
    fileType: dto.file_type,
    fileSize: dto.file_size,
    processingStatus: dto.processing_status,
    processingError: dto.processing_error,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}
